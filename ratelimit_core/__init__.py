"""
RateLimit-Core: Production-Ready Rate Limiting for Python & FastAPI/ASGI.
"""

from ratelimit_core.algorithms import (
    BaseRateLimiterAlgorithm,
    FixedWindow,
    LeakyBucket,
    SlidingWindowCounter,
    TokenBucket,
)
from ratelimit_core.exceptions import (
    ConfigurationError,
    RateLimitError,
    RateLimitExceeded,
    StorageBackendError,
)
from ratelimit_core.integrations import (
    KeyExtractor,
    RateLimiterDependency,
    RateLimitMiddleware,
    client_ip_extractor,
    get_client_ip,
    header_extractor,
    path_and_ip_extractor,
    rate_limit,
)
from ratelimit_core.metrics import (
    get_latest_metrics,
    record_backend_error,
    record_circuit_breaker_state,
    record_metric,
)
from ratelimit_core.models import RateLimitResult, RateLimitRule
from ratelimit_core.rules.manager import DynamicRuleManager
from ratelimit_core.storage import (
    BaseStorageBackend,
    CircuitBreaker,
    CircuitState,
    MemoryStorageBackend,
    RedisStorageBackend,
)

__version__ = "0.1.0"

__all__ = [
    # Models & Exceptions
    "RateLimitRule",
    "RateLimitResult",
    "RateLimitError",
    "RateLimitExceeded",
    "StorageBackendError",
    "ConfigurationError",
    # Storage Backends & Resilience
    "BaseStorageBackend",
    "MemoryStorageBackend",
    "RedisStorageBackend",
    "CircuitBreaker",
    "CircuitState",
    # Algorithms
    "BaseRateLimiterAlgorithm",
    "TokenBucket",
    "SlidingWindowCounter",
    "FixedWindow",
    "LeakyBucket",
    # Rules & Metrics
    "DynamicRuleManager",
    "get_latest_metrics",
    "record_metric",
    "record_circuit_breaker_state",
    "record_backend_error",
    # Integrations
    "RateLimitMiddleware",
    "RateLimiterDependency",
    "rate_limit",
    "KeyExtractor",
    "client_ip_extractor",
    "get_client_ip",
    "header_extractor",
    "path_and_ip_extractor",
]

