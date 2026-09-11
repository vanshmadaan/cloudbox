from __future__ import annotations

import time
from typing import Optional

from ratelimit_core.algorithms.base import BaseRateLimiterAlgorithm
from ratelimit_core.models import RateLimitResult, RateLimitRule
from ratelimit_core.storage.base import BaseStorageBackend
from ratelimit_core.storage.lua_scripts import LEAKY_BUCKET_LUA
from ratelimit_core.storage.memory import MemoryStorageBackend
from ratelimit_core.storage.redis_backend import RedisStorageBackend


class LeakyBucket(BaseRateLimiterAlgorithm):
    """
    Leaky Bucket Algorithm.
    Shapes traffic to a smooth constant outflow rate (`rate / period`).
    Excess requests queue up in the bucket up to `capacity`; overflows are dropped.
    """

    def __init__(self, rule: RateLimitRule, backend: BaseStorageBackend) -> None:
        super().__init__(rule, backend)
        self.leak_rate = self.rule.rate / self.rule.period
        self.capacity = float(self.rule.max_capacity)

    async def acquire(self, key: str, cost: Optional[int] = None) -> RateLimitResult:
        c = cost if cost is not None else self.rule.cost
        now = time.time()
        ttl = (self.capacity / self.leak_rate) * 2
        storage_key = f"lb:{key}"

        if isinstance(self.backend, RedisStorageBackend):
            res = await self.backend.eval_script(
                LEAKY_BUCKET_LUA,
                [storage_key],
                [self.capacity, self.leak_rate, c, now, ttl],
            )
            allowed = bool(res[0] == 1)
            remaining = int(res[1])
            reset_after = float(res[2])
            retry_after = float(res[3]) if not allowed else None
            return RateLimitResult(
                allowed=allowed,
                limit=int(self.capacity),
                remaining=remaining,
                reset_after=reset_after,
                retry_after=retry_after,
                metadata={"algorithm": "leaky_bucket"},
            )

        elif isinstance(self.backend, MemoryStorageBackend):
            async with self.backend.lock:
                state = self.backend.get_state(storage_key)
                if "water" not in state:
                    water = 0.0
                    last_leak = now
                else:
                    water = state["water"]
                    last_leak = state["last_leak"]
                    delta = max(0.0, now - last_leak)
                    water = max(0.0, water - (delta * self.leak_rate))

                if water + c <= self.capacity:
                    water += c
                    allowed = True
                    retry_after = None
                else:
                    allowed = False
                    retry_after = (water + c - self.capacity) / self.leak_rate

                remaining = max(0, int(self.capacity - water))
                reset_after = water / self.leak_rate if self.leak_rate > 0 else 0.0

                state["water"] = water
                state["last_leak"] = now
                self.backend.set_state_expiry(storage_key, ttl)

                return RateLimitResult(
                    allowed=allowed,
                    limit=int(self.capacity),
                    remaining=remaining,
                    reset_after=reset_after,
                    retry_after=retry_after,
                    metadata={"algorithm": "leaky_bucket"},
                )
        else:
            raise NotImplementedError(f"Unsupported backend: {type(self.backend)}")

