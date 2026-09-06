from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class StorageBackend(ABC):
    """Abstract interface for object storage operations."""

    @abstractmethod
    async def generate_presigned_upload_url(
        self,
        key: str,
        content_type: str = "application/octet-stream",
        expires_in: int = 3600,
    ) -> Dict[str, Any]:
        """Generate a presigned URL/parameters allowing clients to upload directly to storage."""
        pass

    @abstractmethod
    async def generate_presigned_download_url(
        self,
        key: str,
        expires_in: int = 3600,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> str:
        """Generate a presigned URL allowing clients to download directly from storage."""
        pass

    @abstractmethod
    async def upload_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> None:
        """Upload raw bytes directly to storage."""
        pass

    @abstractmethod
    async def download_bytes(self, key: str) -> bytes:
        """Download raw bytes from storage."""
        pass

    @abstractmethod
    async def delete_object(self, key: str) -> None:
        """Delete an object from storage."""
        pass

    @abstractmethod
    async def head_object(self, key: str) -> Dict[str, Any]:
        """Retrieve metadata for an object in storage."""
        pass

    @abstractmethod
    async def object_exists(self, key: str) -> bool:
        """Check if an object exists in storage."""
        pass

    @abstractmethod
    async def copy_object(self, source_key: str, destination_key: str) -> None:
        """Copy an object within storage."""
        pass

