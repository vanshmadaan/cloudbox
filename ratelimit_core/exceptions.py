from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ratelimit_core.models import RateLimitResult


class RateLimitError(Exception):
    """Base exception for all rate limiting errors."""


class RateLimitExceeded(RateLimitError):
    """Raised when a request exceeds configured rate limits."""

    def __init__(self, message: str, result: RateLimitResult) -> None:
        super().__init__(message)
        self.result = result


class StorageBackendError(RateLimitError):
    """Raised when a storage backend encounters a connection or operational error."""


class ConfigurationError(RateLimitError):
    """Raised when rate limiter is configured improperly."""

