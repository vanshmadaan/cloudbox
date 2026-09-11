from __future__ import annotations

import time
from typing import Optional

from ratelimit_core.algorithms.base import BaseRateLimiterAlgorithm
from ratelimit_core.models import RateLimitResult, RateLimitRule
from ratelimit_core.storage.base import BaseStorageBackend
from ratelimit_core.storage.lua_scripts import SLIDING_WINDOW_COUNTER_LUA
from ratelimit_core.storage.memory import MemoryStorageBackend
from ratelimit_core.storage.redis_backend import RedisStorageBackend


class SlidingWindowCounter(BaseRateLimiterAlgorithm):
    """
    Sliding Window Counter Algorithm (Cloudflare/Stripe approximation).
    Blends previous and current window counts based on elapsed time within the window.
    Prevents the boundary burst issue of Fixed Window with low O(1) memory.
    """

    def __init__(self, rule: RateLimitRule, backend: BaseStorageBackend) -> None:
        super().__init__(rule, backend)
        self.period = float(self.rule.period)
        self.limit = int(self.rule.rate)

    async def acquire(self, key: str, cost: Optional[int] = None) -> RateLimitResult:
        c = cost if cost is not None else self.rule.cost
        now = time.time()

        if isinstance(self.backend, RedisStorageBackend):
            res = await self.backend.eval_script(
                SLIDING_WINDOW_COUNTER_LUA,
                [f"sw:{key}"],
                [self.limit, self.period, c, now],
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
                metadata={"algorithm": "sliding_window_counter"},
            )

        elif isinstance(self.backend, MemoryStorageBackend):
            storage_key = f"sw:{key}"
            current_window = int(now // self.period)
            prev_window = current_window - 1
            time_into_current = now - (current_window * self.period)
            prev_weight = max(0.0, (self.period - time_into_current) / self.period)

            async with self.backend.lock:
                state = self.backend.get_state(storage_key)
                curr_key = str(current_window)
                prev_key = str(prev_window)
                curr_count = state.get(curr_key, 0)
                prev_count = state.get(prev_key, 0)

                estimated_count = curr_count + (prev_count * prev_weight)
                reset_after = self.period - time_into_current

                if estimated_count + c <= self.limit:
                    state[curr_key] = curr_count + c
                    # Purge outdated windows
                    keys_to_remove = [
                        k for k in list(state.keys())
                        if k.isdigit() and int(k) < prev_window
                    ]
                    for k in keys_to_remove:
                        state.pop(k, None)

                    self.backend.set_state_expiry(storage_key, self.period * 2)
                    allowed = True
                    remaining = max(0, int(self.limit - estimated_count - c))
                    retry_after = None
                else:
                    allowed = False
                    remaining = 0
                    retry_estimate = max(0.1, reset_after * ((estimated_count + c - self.limit) / (prev_count + 1)))
                    retry_after = min(retry_estimate, reset_after)

                return RateLimitResult(
                    allowed=allowed,
                    limit=self.limit,
                    remaining=remaining,
                    reset_after=reset_after,
                    retry_after=retry_after,
                    metadata={"algorithm": "sliding_window_counter"},
                )
        else:
            raise NotImplementedError(f"Unsupported backend: {type(self.backend)}")

