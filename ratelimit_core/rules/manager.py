"""
Dynamic Rule Manager for runtime rate limit administration.
Allows updating tier limits, user quotas, and resetting client blocks without downtime.
"""

from __future__ import annotations

import json
from typing import Optional

from ratelimit_core.models import RateLimitRule
from ratelimit_core.storage.base import BaseStorageBackend
from ratelimit_core.storage.redis_backend import RedisStorageBackend


class DynamicRuleManager:
    """
    Manages rate limiting rules dynamically backed by Redis or In-Memory storage.
    """

    def __init__(
        self,
        backend: BaseStorageBackend,
        rule_prefix: str = "dynrule",
    ) -> None:
        self.backend = backend
        self.rule_prefix = rule_prefix

    def _rule_key(self, identifier: str) -> str:
        return f"{self.rule_prefix}:{identifier}"

    async def set_rule(self, identifier: str, rule: RateLimitRule) -> None:
        """Persist or update a dynamic rate limit rule."""
        payload = {
            "rate": rule.rate,
            "period": rule.period,
            "capacity": rule.capacity,
            "cost": rule.cost,
        }
        await self.backend.set(self._rule_key(identifier), json.dumps(payload))

    async def get_rule(
        self,
        identifier: str,
        default: Optional[RateLimitRule] = None,
    ) -> Optional[RateLimitRule]:
        """Fetch a dynamic rule, or return default if not explicitly configured."""
        raw = await self.backend.get(self._rule_key(identifier))
        if raw is None:
            return default

        data = json.loads(raw)
        return RateLimitRule(
            rate=int(data["rate"]),
            period=float(data["period"]),
            capacity=data.get("capacity"),
            cost=int(data.get("cost", 1)),
        )

    async def delete_rule(self, identifier: str) -> bool:
        """Delete a dynamic rule."""
        return await self.backend.delete(self._rule_key(identifier))

    async def reset_client_quota(self, client_key: str) -> int:
        """
        Instantly unblock a rate-limited client by removing stored algorithm keys.
        Returns the number of keys cleared.
        """
        cleared_count = 0
        prefixes = [f"tb:{client_key}", f"sw:{client_key}", f"lb:{client_key}"]

        for p in prefixes:
            if await self.backend.delete(p):
                cleared_count += 1

        # Also attempt to reset route-prefixed keys if Redis using non-blocking SCAN
        if isinstance(self.backend, RedisStorageBackend):
            prefix = self.backend.key_prefix
            pattern = f"{prefix}:*{client_key}*" if prefix else f"*{client_key}*"
            client = self.backend.client
            batch: list[str] = []
            async for k in client.scan_iter(match=pattern, count=100):
                key_str = k.decode() if isinstance(k, bytes) else str(k)
                batch.append(key_str)
                if len(batch) >= 500:
                    await client.delete(*batch)
                    cleared_count += len(batch)
                    batch = []
            if batch:
                await client.delete(*batch)
                cleared_count += len(batch)

        return cleared_count

