from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ratelimit_core.models import RateLimitResult, RateLimitRule
from ratelimit_core.storage.base import BaseStorageBackend


class BaseRateLimiterAlgorithm(ABC):
    """
    Abstract base class for all rate limiting algorithms.
    """

    def __init__(self, rule: RateLimitRule, backend: BaseStorageBackend) -> None:
        self.rule = rule
        self.backend = backend

    @abstractmethod
    async def acquire(self, key: str, cost: Optional[int] = None) -> RateLimitResult:
        """
        Attempt to consume `cost` units for `key`.
        Returns RateLimitResult indicating whether request is allowed and metadata.
        """

