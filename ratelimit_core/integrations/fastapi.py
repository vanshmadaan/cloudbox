from __future__ import annotations

import time
from functools import wraps
from typing import Any, Callable, List, Optional, Type

from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ratelimit_core.algorithms.base import BaseRateLimiterAlgorithm
from ratelimit_core.algorithms.token_bucket import TokenBucket
from ratelimit_core.integrations.key_extractors import KeyExtractor, get_client_ip
from ratelimit_core.metrics import record_metric
from ratelimit_core.models import RateLimitResult, RateLimitRule
from ratelimit_core.storage.base import BaseStorageBackend


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    ASGI HTTP Middleware for global rate limiting in FastAPI/Starlette applications.
    Automatically injects RFC-compliant rate limit headers into all responses and
    returns standard HTTP 429 Too Many Requests when limits are exceeded.
    """

    def __init__(
        self,
        app: Any,
        limiter: BaseRateLimiterAlgorithm,
        key_extractor: KeyExtractor = get_client_ip,
        exclude_paths: Optional[List[str]] = None,
        custom_headers: bool = True,
    ) -> None:
        super().__init__(app)
        self.limiter = limiter
        self.key_extractor = key_extractor
        self.exclude_paths = set(exclude_paths or ["/docs", "/redoc", "/openapi.json", "/health", "/metrics"])
        self.custom_headers = custom_headers

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if any(request.url.path.startswith(prefix) for prefix in self.exclude_paths):
            return await call_next(request)

        key = self.key_extractor(request)
        t0 = time.perf_counter()
        result: RateLimitResult = await self.limiter.acquire(key)
        duration = time.perf_counter() - t0

        record_metric(
            allowed=result.allowed,
            algorithm=result.metadata.get("algorithm", "unknown"),
            route=request.url.path,
            duration=duration,
            remaining=result.remaining,
        )

        if not result.allowed:
            headers = result.to_headers() if self.custom_headers else {}
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too Many Requests",
                    "retry_after": result.retry_after,
                    "limit": result.limit,
                },
                headers=headers,
            )

        response = await call_next(request)
        if self.custom_headers:
            for k, v in result.to_headers().items():
                response.headers[k] = v
        return response


class RateLimiterDependency:
    """
    FastAPI Dependency for per-route rate limiting.
    Usage:
        limiter = RateLimiterDependency(rule=RateLimitRule(rate=5, period=60), backend=backend)
        @app.get("/items", dependencies=[Depends(limiter)])
    """

    def __init__(
        self,
        rule: RateLimitRule,
        backend: BaseStorageBackend,
        algorithm_cls: Type[BaseRateLimiterAlgorithm] = TokenBucket,
        key_extractor: KeyExtractor = get_client_ip,
        cost: int = 1,
        prefix: str = "route",
    ) -> None:
        self.algorithm = algorithm_cls(rule=rule, backend=backend)
        self.key_extractor = key_extractor
        self.cost = cost
        self.prefix = prefix

    async def __call__(self, request: Request, response: Response) -> RateLimitResult:
        key_suffix = self.key_extractor(request)
        route_key = f"{self.prefix}:{request.method}:{request.url.path}:{key_suffix}"
        t0 = time.perf_counter()
        result = await self.algorithm.acquire(key=route_key, cost=self.cost)
        duration = time.perf_counter() - t0

        record_metric(
            allowed=result.allowed,
            algorithm=result.metadata.get("algorithm", "unknown"),
            route=request.url.path,
            duration=duration,
            remaining=result.remaining,
        )

        for header_name, header_val in result.to_headers().items():
            response.headers[header_name] = header_val

        if not result.allowed:
            raise HTTPException(
                status_code=429,
                detail="Too Many Requests",
                headers=result.to_headers(),
            )
        return result


def rate_limit(
    rule: RateLimitRule,
    backend: BaseStorageBackend,
    algorithm_cls: Type[BaseRateLimiterAlgorithm] = TokenBucket,
    key_extractor: KeyExtractor = get_client_ip,
    cost: int = 1,
    prefix: str = "endpoint",
) -> Callable[..., Any]:
    """
    Decorator for FastAPI endpoint functions.
    Usage:
        @app.get("/items")
        @rate_limit(rule=RateLimitRule(rate=10, period=60), backend=backend)
        async def get_items():
            return {"status": "ok"}
    """
    dependency = RateLimiterDependency(
        rule=rule,
        backend=backend,
        algorithm_cls=algorithm_cls,
        key_extractor=key_extractor,
        cost=cost,
        prefix=prefix,
    )

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Look for request and response in kwargs
            request: Optional[Request] = kwargs.get("request")
            response: Optional[Response] = kwargs.get("response")

            if request is None:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break

            if response is None:
                for arg in args:
                    if isinstance(arg, Response):
                        response = arg
                        break

            if request is not None:
                dummy_response = response or Response()
                await dependency(request, dummy_response)

            return await func(*args, **kwargs)

        return wrapper

    return decorator

