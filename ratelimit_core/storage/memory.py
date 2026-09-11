from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

from ratelimit_core.storage.base import BaseStorageBackend


class MemoryStorageBackend(BaseStorageBackend):
    """
    Asyncio-safe, in-memory storage backend with automatic TTL expiration.
    Ideal for local development, single-instance services, and unit testing.
    """

    def __init__(self, cleanup_interval_seconds: float = 60.0) -> None:
        self.cleanup_interval_seconds = cleanup_interval_seconds
        self._lock = asyncio.Lock()
        self._store: Dict[str, Tuple[str, Optional[float]]] = {}
        # Dedicated custom state dict for rate-limiting algorithms
        self._state: Dict[str, Dict[str, Any]] = {}
        self._state_expires: Dict[str, float] = {}
        self._cleanup_task: Optional[asyncio.Task[None]] = None

    async def initialize(self) -> None:
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())

    async def close(self) -> None:
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    def get_state(self, key: str) -> Dict[str, Any]:
        """Internal helper to get mutable state dictionary for a key."""
        now = time.time()
        # Check expired
        if key in self._state_expires and self._state_expires[key] <= now:
            self._state.pop(key, None)
            self._state_expires.pop(key, None)

        if key not in self._state:
            self._state[key] = {}
        return self._state[key]

    def set_state_expiry(self, key: str, ttl_seconds: float) -> None:
        """Internal helper to set expiration on algorithm state."""
        self._state_expires[key] = time.time() + ttl_seconds

    async def _periodic_cleanup(self) -> None:
        """Periodically purge expired keys to prevent memory leaks."""
        while True:
            try:
                await asyncio.sleep(self.cleanup_interval_seconds)
                now = time.time()
                async with self._lock:
                    # Clean generic store
                    expired_keys = [
                        k for k, (_, exp) in self._store.items()
                        if exp is not None and exp <= now
                    ]
                    for k in expired_keys:
                        self._store.pop(k, None)

                    # Clean algorithm state
                    expired_state = [
                        k for k, exp in self._state_expires.items()
                        if exp <= now
                    ]
                    for k in expired_state:
                        self._state.pop(k, None)
                        self._state_expires.pop(k, None)
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    async def eval_script(
        self,
        script: str,
        keys: List[str],
        args: List[Any],
    ) -> Any:
        raise NotImplementedError(
            "eval_script is only supported on RedisStorageBackend. "
            "Use native algorithm implementations with MemoryStorageBackend."
        )

    async def get(self, key: str) -> Optional[str]:
        async with self._lock:
            if key not in self._store:
                return None
            val, exp = self._store[key]
            if exp is not None and exp <= time.time():
                del self._store[key]
                return None
            return val

    async def set(
        self,
        key: str,
        value: str,
        expire_seconds: Optional[float] = None,
    ) -> None:
        async with self._lock:
            exp = time.time() + expire_seconds if expire_seconds is not None else None
            self._store[key] = (value, exp)

    async def delete(self, key: str) -> bool:
        async with self._lock:
            in_store = key in self._store
            in_state = key in self._state
            self._store.pop(key, None)
            self._state.pop(key, None)
            self._state_expires.pop(key, None)
            return in_store or in_state

    async def flush_all(self) -> None:
        async with self._lock:
            self._store.clear()
            self._state.clear()
            self._state_expires.clear()

