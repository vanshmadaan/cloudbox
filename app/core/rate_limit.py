from __future__ import annotations

from typing import Optional

from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings
from app.core.logging import logger
from ratelimit_core import (
    BaseStorageBackend,
    MemoryStorageBackend,
    RateLimitMiddleware,
    RateLimiterDependency,
    RateLimitResult,
    RateLimitRule,
    RedisStorageBackend,
    TokenBucket,
    get_client_ip,
)


def get_storage_backend() -> BaseStorageBackend:
    """
    Initialize storage backend for rate limiting.
    Uses RedisStorageBackend when REDIS_URL is configured (e.g. AWS ElastiCache / Redis in production),
    and falls back to MemoryStorageBackend for local development and test environments.
    """
    should_use_redis = settings.RATE_LIMIT_STORAGE == "redis" or (
        settings.RATE_LIMIT_STORAGE == "auto" and bool(settings.REDIS_URL)
    )

    if should_use_redis and settings.REDIS_URL:
        try:
            backend = RedisStorageBackend(
                redis_url=settings.REDIS_URL,
                socket_timeout=1.5,
                enable_circuit_breaker=True,
            )
            logger.info("Rate limiter initialized with distributed RedisStorageBackend.")
            return backend
        except Exception as exc:
            logger.warning(
                f"Failed to connect to Redis for rate limiting ({exc}). Falling back to MemoryStorageBackend."
            )

    logger.info("Rate limiter initialized with MemoryStorageBackend.")
    return MemoryStorageBackend()


# Initialize shared storage backend
storage_backend = get_storage_backend()


class OptionalRateLimiterDependency(RateLimiterDependency):
    """RateLimiterDependency that respects settings.RATE_LIMIT_ENABLED."""

    async def __call__(self, request: Request, response: Response) -> Optional[RateLimitResult]:
        if not settings.RATE_LIMIT_ENABLED:
            return None
        return await super().__call__(request, response)


class OptionalRateLimitMiddleware(RateLimitMiddleware):
    """RateLimitMiddleware that respects settings.RATE_LIMIT_ENABLED."""

    async def dispatch(self, request: Request, call_next):
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)
        return await super().dispatch(request, call_next)


# 1. Global Default Limiter (for general API traffic)
global_rule = RateLimitRule(
    rate=settings.RATE_LIMIT_DEFAULT_RATE,
    period=settings.RATE_LIMIT_DEFAULT_PERIOD,
    capacity=max(20, settings.RATE_LIMIT_DEFAULT_RATE // 4),
)
global_limiter = TokenBucket(rule=global_rule, backend=storage_backend)

# 2. Strict Authentication Limiter (/auth/login)
auth_rule = RateLimitRule(
    rate=settings.RATE_LIMIT_AUTH_RATE,
    period=settings.RATE_LIMIT_AUTH_PERIOD,
    capacity=max(1, settings.RATE_LIMIT_AUTH_RATE // 2),
)
auth_rate_limiter = OptionalRateLimiterDependency(
    rule=auth_rule,
    backend=storage_backend,
    key_extractor=get_client_ip,
    prefix="auth_login",
)

# 3. OTP & Password Reset Limiter (/auth/forgot-password, /auth/reset-password)
otp_rule = RateLimitRule(
    rate=settings.RATE_LIMIT_OTP_RATE,
    period=settings.RATE_LIMIT_OTP_PERIOD,
    capacity=1,
)
otp_rate_limiter = OptionalRateLimiterDependency(
    rule=otp_rule,
    backend=storage_backend,
    key_extractor=get_client_ip,
    prefix="auth_otp",
)

# 4. Upload Initiation Limiter (/files/upload/initiate)
upload_rule = RateLimitRule(
    rate=settings.RATE_LIMIT_UPLOAD_RATE,
    period=settings.RATE_LIMIT_UPLOAD_PERIOD,
    capacity=max(2, settings.RATE_LIMIT_UPLOAD_RATE // 4),
)
upload_rate_limiter = OptionalRateLimiterDependency(
    rule=upload_rule,
    backend=storage_backend,
    key_extractor=get_client_ip,
    prefix="file_upload",
)

