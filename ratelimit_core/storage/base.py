from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, List, Optional


class BaseStorageBackend(ABC):
    """
    Abstract Base Class for Rate Limiter Storage Backends.
    All storage backends must provide asynchronous methods for state management.
    """

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize connections or background workers."""

    @abstractmethod
    async def close(self) -> None:
        """Close connections and cleanup resources."""

    @abstractmethod
    async def eval_script(
        self,
        script: str,
        keys: List[str],
        args: List[Any],
    ) -> Any:
        """
        Execute an atomic script (e.g., Lua script for Redis).
        For backends supporting scripts, this ensures atomic evaluation.
        """

    @abstractmethod
    async def get(self, key: str) -> Optional[str]:
        """Retrieve the string value for a key."""

    @abstractmethod
    async def set(
        self,
        key: str,
        value: str,
        expire_seconds: Optional[float] = None,
    ) -> None:
        """Set a key with an optional expiration in seconds."""

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete a key. Returns True if key existed."""

    @abstractmethod
    async def flush_all(self) -> None:
        """Clear all stored rate limiting data (primarily for testing)."""

