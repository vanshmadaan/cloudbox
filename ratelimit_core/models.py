from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class RateLimitRule:
    """
    Defines the parameters of a rate limit.

    Attributes:
        rate: The number of requests permitted within the period.
        period: The window period in seconds (e.g., 60 for 1 minute).
        capacity: Maximum burst capacity (useful for Token Bucket and Leaky Bucket).
                  Defaults to `rate` if not explicitly specified.
        cost: Default cost of a single request (default: 1).
    """
    rate: int
    period: float
    capacity: Optional[int] = None
    cost: int = 1

    def __post_init__(self) -> None:
        if self.rate <= 0:
            raise ValueError(f"Rate must be positive, got {self.rate}")
        if self.period <= 0:
            raise ValueError(f"Period must be positive, got {self.period}")
        if self.capacity is not None and self.capacity <= 0:
            raise ValueError(f"Capacity must be positive, got {self.capacity}")
        if self.cost <= 0:
            raise ValueError(f"Cost must be positive, got {self.cost}")

    @property
    def max_capacity(self) -> int:
        return self.capacity if self.capacity is not None else self.rate


@dataclass(frozen=True)
class RateLimitResult:
    """
    Result of evaluating a rate limit request.

    Attributes:
        allowed: True if request is allowed, False if rate limited.
        limit: The total limit for the given rule.
        remaining: How many requests remaining in current window/bucket.
        reset_after: Floating seconds until window resets or bucket is full.
        retry_after: Floating seconds client must wait before retrying (if denied).
        metadata: Optional dictionary with algorithm-specific diagnostics.
    """
    allowed: bool
    limit: int
    remaining: int
    reset_after: float
    retry_after: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_headers(self) -> Dict[str, str]:
        """
        Generate standard HTTP response headers for rate limiting.
        Follows IETF / RFC 6585 and GitHub/Stripe standard conventions.
        """
        now = time.time()
        reset_timestamp = int(now + max(0.0, self.reset_after))
        headers: Dict[str, str] = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(max(0, self.remaining)),
            "X-RateLimit-Reset": str(reset_timestamp),
        }
        if not self.allowed and self.retry_after is not None:
            # Retry-After header in seconds (integer ceil)
            headers["Retry-After"] = str(max(1, int(self.retry_after + 0.999)))
        return headers

