import pytest
from httpx import AsyncClient
from app.core.config import settings
from app.core.rate_limit import (
    auth_rate_limiter,
    global_limiter,
    otp_rate_limiter,
    upload_rate_limiter,
    get_storage_backend,
)
from ratelimit_core import (
    MemoryStorageBackend,
    RateLimitRule,
    TokenBucket,
)


def configure_token_bucket(limiter: TokenBucket, rule: RateLimitRule, backend: MemoryStorageBackend):
    """Helper to update TokenBucket rule and capacity dynamically for tests."""
    limiter.rule = rule
    limiter.capacity = float(rule.max_capacity)
    limiter.refill_rate = rule.rate / rule.period
    limiter.backend = backend


@pytest.mark.asyncio
async def test_storage_backend_fallback():
    """Verify get_storage_backend() gracefully falls back to MemoryStorageBackend."""
    backend = get_storage_backend()
    assert isinstance(backend, MemoryStorageBackend)


@pytest.mark.asyncio
async def test_global_rate_limiter_middleware(client: AsyncClient):
    """
    Verify Global RateLimitMiddleware injects rate limit headers on allowed requests
    and returns HTTP 429 Too Many Requests when the quota is exceeded.
    """
    settings.RATE_LIMIT_ENABLED = True

    # Use a small test rule for fast deterministic testing
    test_backend = MemoryStorageBackend()
    test_rule = RateLimitRule(rate=3, period=60.0, capacity=3)
    configure_token_bucket(global_limiter, test_rule, test_backend)

    try:
        # First 3 requests should be allowed
        for i in range(3):
            resp = await client.get("/")
            assert resp.status_code == 200, f"Request {i+1} failed with {resp.status_code}"
            assert "x-ratelimit-limit" in resp.headers
            assert "x-ratelimit-remaining" in resp.headers
            assert "x-ratelimit-reset" in resp.headers
            remaining = int(resp.headers["x-ratelimit-remaining"])
            assert remaining == 2 - i

        # 4th request must be throttled with HTTP 429
        resp = await client.get("/")
        assert resp.status_code == 429
        assert "retry-after" in resp.headers
        data = resp.json()
        assert data.get("detail") == "Too Many Requests"
        assert "retry_after" in data
    finally:
        settings.RATE_LIMIT_ENABLED = False


@pytest.mark.asyncio
async def test_rate_limit_excluded_paths(client: AsyncClient):
    """
    Verify whitelisted paths (/api/v1/health, /docs, /static) are NEVER throttled.
    """
    settings.RATE_LIMIT_ENABLED = True

    # Exhaust global limiter
    test_backend = MemoryStorageBackend()
    test_rule = RateLimitRule(rate=1, period=60.0, capacity=1)
    configure_token_bucket(global_limiter, test_rule, test_backend)

    try:
        # Exhaust single token
        await client.get("/")
        assert (await client.get("/")).status_code == 429

        # Excluded health endpoint must still respond with 200 OK
        health_resp = await client.get("/api/v1/health")
        assert health_resp.status_code == 200
        assert health_resp.json().get("status") in ("online", "healthy")
    finally:
        settings.RATE_LIMIT_ENABLED = False


@pytest.mark.asyncio
async def test_auth_route_rate_limiting(client: AsyncClient):
    """
    Verify sensitive auth endpoint (/api/v1/auth/login) enforces strict per-route limits.
    """
    settings.RATE_LIMIT_ENABLED = True

    test_backend = MemoryStorageBackend()
    # 2 requests per minute limit
    test_rule = RateLimitRule(rate=2, period=60.0, capacity=2)
    auth_rate_limiter.algorithm = TokenBucket(rule=test_rule, backend=test_backend)

    # Relax global limiter so it doesn't interfere
    relax_rule = RateLimitRule(rate=1000, period=60.0, capacity=1000)
    configure_token_bucket(global_limiter, relax_rule, test_backend)

    try:
        login_payload = {"email": "rate_test@example.com", "password": "WrongPassword123!"}

        # Request 1: 401 Unauthorized (allowed through to auth service)
        resp1 = await client.post("/api/v1/auth/login", json=login_payload)
        assert resp1.status_code in (401, 404)
        assert "x-ratelimit-remaining" in resp1.headers

        # Request 2: 401 Unauthorized (allowed through to auth service)
        resp2 = await client.post("/api/v1/auth/login", json=login_payload)
        assert resp2.status_code in (401, 404)

        # Request 3: Exceeded limit -> 429 Too Many Requests
        resp3 = await client.post("/api/v1/auth/login", json=login_payload)
        assert resp3.status_code == 429
        assert "Too Many Requests" in resp3.text
    finally:
        settings.RATE_LIMIT_ENABLED = False


@pytest.mark.asyncio
async def test_otp_route_rate_limiting(client: AsyncClient):
    """
    Verify OTP endpoint (/api/v1/auth/forgot-password/send-otp) protects SES and enforces limits.
    """
    settings.RATE_LIMIT_ENABLED = True

    # Register user first so the endpoint logic succeeds
    email = "otp_rate_user@example.com"
    await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "Password123!", "full_name": "OTP User"},
    )

    test_backend = MemoryStorageBackend()
    # 1 request per 10 minutes limit
    test_rule = RateLimitRule(rate=1, period=600.0, capacity=1)
    otp_rate_limiter.algorithm = TokenBucket(rule=test_rule, backend=test_backend)

    relax_rule = RateLimitRule(rate=1000, period=60.0, capacity=1000)
    configure_token_bucket(global_limiter, relax_rule, test_backend)

    try:
        otp_payload = {"email": email}

        # Request 1: Allowed (returns 200 OK)
        resp1 = await client.post("/api/v1/auth/forgot-password/send-otp", json=otp_payload)
        assert resp1.status_code == 200

        # Request 2: Throttled -> 429 Too Many Requests
        resp2 = await client.post("/api/v1/auth/forgot-password/send-otp", json=otp_payload)
        assert resp2.status_code == 429
        assert "Too Many Requests" in resp2.text
    finally:
        settings.RATE_LIMIT_ENABLED = False


@pytest.mark.asyncio
async def test_upload_route_rate_limiting(client: AsyncClient, auth_headers: dict):
    """
    Verify upload initiation (/api/v1/files/upload-url) enforces per-route upload rate limits.
    """
    settings.RATE_LIMIT_ENABLED = True

    test_backend = MemoryStorageBackend()
    # 2 upload requests per minute limit
    test_rule = RateLimitRule(rate=2, period=60.0, capacity=2)
    upload_rate_limiter.algorithm = TokenBucket(rule=test_rule, backend=test_backend)

    relax_rule = RateLimitRule(rate=1000, period=60.0, capacity=1000)
    configure_token_bucket(global_limiter, relax_rule, test_backend)

    try:
        upload_payload = {
            "name": "ratelimit_doc.pdf",
            "content_type": "application/pdf",
            "file_size": 1024,
        }

        # Request 1: Allowed (returns 200 OK)
        resp1 = await client.post("/api/v1/files/upload-url", json=upload_payload, headers=auth_headers)
        assert resp1.status_code == 200
        assert "upload_url" in resp1.json()

        # Request 2: Allowed (returns 200 OK)
        resp2 = await client.post("/api/v1/files/upload-url", json=upload_payload, headers=auth_headers)
        assert resp2.status_code == 200

        # Request 3: Throttled -> 429 Too Many Requests
        resp3 = await client.post("/api/v1/files/upload-url", json=upload_payload, headers=auth_headers)
        assert resp3.status_code == 429
        assert "Too Many Requests" in resp3.text
    finally:
        settings.RATE_LIMIT_ENABLED = False

