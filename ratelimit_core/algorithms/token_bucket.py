from __future__ import annotations

import time
from typing import Optional

from ratelimit_core.algorithms.base import BaseRateLimiterAlgorithm
from ratelimit_core.models import RateLimitResult, RateLimitRule
from ratelimit_core.storage.base import BaseStorageBackend
from ratelimit_core.storage.lua_scripts import TOKEN_BUCKET_LUA
from ratelimit_core.storage.memory import MemoryStorageBackend
from ratelimit_core.storage.redis_backend import RedisStorageBackend


class TokenBucket(BaseRateLimiterAlgorithm):
    """
    Token Bucket Algorithm.
    Allows bursts of traffic up to `capacity`, replenishing tokens smoothly at `rate / period`.
    Ideal for general API rate limiting where short bursts of requests are acceptable.
    """

    def __init__(self, rule: RateLimitRule, backend: BaseStorageBackend) -> None:
        super().__init__(rule, backend)
        self.refill_rate = self.rule.rate / self.rule.period
        self.capacity = float(self.rule.max_capacity)

    async def acquire(self, key: str, cost: Optional[int] = None) -> RateLimitResult:
        c = cost if cost is not None else self.rule.cost
        now = time.time()
        ttl = (self.capacity / self.refill_rate) * 2

        if isinstance(self.backend, RedisStorageBackend):
            res = await self.backend.eval_script(
                TOKEN_BUCKET_LUA,
                [f"tb:{key}"],
                [self.capacity, self.refill_rate, c, now, ttl],
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
                metadata={"algorithm": "token_bucket"},
            )

        elif isinstance(self.backend, MemoryStorageBackend):
            storage_key = f"tb:{key}"
            async with self.backend.lock:
                state = self.backend.get_state(storage_key)
                if "tokens" not in state:
                    tokens = self.capacity
                    last_updated = now
                else:
                    tokens = state["tokens"]
                    last_updated = state["last_updated"]
                    delta = max(0.0, now - last_updated)
                    tokens = min(self.capacity, tokens + (delta * self.refill_rate))

                if tokens >= c:
                    tokens -= c
                    allowed = True
                    retry_after = None
                else:
                    allowed = False
                    retry_after = (c - tokens) / self.refill_rate

                remaining = max(0, int(tokens))
                reset_after = (self.capacity - tokens) / self.refill_rate

                state["tokens"] = tokens
                state["last_updated"] = now
                self.backend.set_state_expiry(storage_key, ttl)

                return RateLimitResult(
                    allowed=allowed,
                    limit=int(self.capacity),
                    remaining=remaining,
                    reset_after=reset_after,
                    retry_after=retry_after,
                    metadata={"algorithm": "token_bucket"},
                )
        else:
            raise NotImplementedError(f"Unsupported backend: {type(self.backend)}")

