from __future__ import annotations

import time
from typing import Optional

from ratelimit_core.algorithms.base import BaseRateLimiterAlgorithm
from ratelimit_core.models import RateLimitResult, RateLimitRule
from ratelimit_core.storage.base import BaseStorageBackend
from ratelimit_core.storage.lua_scripts import FIXED_WINDOW_LUA
from ratelimit_core.storage.memory import MemoryStorageBackend
from ratelimit_core.storage.redis_backend import RedisStorageBackend


class FixedWindow(BaseRateLimiterAlgorithm):
    """
    Fixed Window Algorithm.
    Counts requests in fixed time buckets (e.g. per minute).
    Extremely simple and low overhead, with window boundary burst caveat.
    """

    def __init__(self, rule: RateLimitRule, backend: BaseStorageBackend) -> None:
        super().__init__(rule, backend)
        self.period = float(self.rule.period)
        self.limit = int(self.rule.rate)

    async def acquire(self, key: str, cost: Optional[int] = None) -> RateLimitResult:
        c = cost if cost is not None else self.rule.cost
        now = time.time()
        window_id = int(now // self.period)
        window_end = (window_id + 1) * self.period
        ttl = max(1.0, window_end - now)
        storage_key = f"fw:{key}:{window_id}"

        if isinstance(self.backend, RedisStorageBackend):
            res = await self.backend.eval_script(
                FIXED_WINDOW_LUA,
                [storage_key],
                [self.limit, c, ttl],
            )
            allowed = bool(res[0] == 1)
            remaining = int(res[1])
            reset_after = float(res[2])
            retry_after = float(res[3]) if not allowed else None
            return RateLimitResult(
                allowed=allowed,
                limit=self.limit,
                remaining=remaining,
                reset_after=reset_after,
                retry_after=retry_after,
                metadata={"algorithm": "fixed_window"},
            )

        elif isinstance(self.backend, MemoryStorageBackend):
            async with self.backend.lock:
                state = self.backend.get_state(storage_key)
                current = state.get("count", 0)

                if current + c <= self.limit:
                    current += c
                    state["count"] = current
                    self.backend.set_state_expiry(storage_key, ttl)
                    allowed = True
                    remaining = self.limit - current
                    retry_after = None
                else:
                    allowed = False
                    remaining = 0
                    retry_after = ttl

                return RateLimitResult(
                    allowed=allowed,
                    limit=self.limit,
                    remaining=remaining,
                    reset_after=ttl,
                    retry_after=retry_after,
                    metadata={"algorithm": "fixed_window"},
                )
        else:
            raise NotImplementedError(f"Unsupported backend: {type(self.backend)}")

