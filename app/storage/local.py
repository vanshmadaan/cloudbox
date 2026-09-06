import os
import aiofiles
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.config import settings
from app.core.exceptions import StorageServiceError
from app.storage.base import StorageBackend


class LocalStorageBackend(StorageBackend):
    """
    Local filesystem storage implementation for offline development and testing.
    """

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = Path(base_dir or settings.LOCAL_STORAGE_DIR).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, key: str) -> Path:
        # Sanitize and resolve key relative to base_dir
        clean_key = key.lstrip("/\\")
        path = (self.base_dir / clean_key).resolve()
        if not str(path).startswith(str(self.base_dir)):
            raise StorageServiceError(
                message="Path traversal attempt detected",
                details={"key": key},
            )
        return path

    async def generate_presigned_upload_url(
        self,
        key: str,
        content_type: str = "application/octet-stream",
        expires_in: int = 3600,
    ) -> Dict[str, Any]:
        # For local backend, provide a local upload endpoint URL or direct PUT simulation
        return {
            "method": "PUT",
            "url": f"/api/v1/files/local-storage-direct-upload?key={key}",
            "headers": {"Content-Type": content_type},
            "key": key,
            "expires_in": expires_in,
        }

    async def generate_presigned_download_url(
        self,
        key: str,
        expires_in: int = 3600,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> str:
        # For local backend, point to a local stream endpoint
        fn_param = f"&filename={filename}" if filename else ""
        return f"/api/v1/files/local-storage-stream?key={key}{fn_param}"

    async def upload_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> None:
        try:
            path = self._get_path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(path, "wb") as f:
                await f.write(data)
        except Exception as e:
            raise StorageServiceError(
                message="Failed to write local file",
                details={"key": key, "error": str(e)},
            ) from e

    async def download_bytes(self, key: str) -> bytes:
        path = self._get_path(key)
        if not path.exists():
            raise StorageServiceError(
                message=f"Object not found: {key}",
                details={"key": key},
            )
        try:
            async with aiofiles.open(path, "rb") as f:
                return await f.read()
        except Exception as e:
            raise StorageServiceError(
                message="Failed to read local file",
                details={"key": key, "error": str(e)},
            ) from e

    async def delete_object(self, key: str) -> None:
        try:
            path = self._get_path(key)
            if path.exists():
                if path.is_file():
                    path.unlink()
                # Clean up empty parent directories up to base_dir
                parent = path.parent
                while parent != self.base_dir and parent.exists():
                    try:
                        parent.rmdir()
                        parent = parent.parent
                    except OSError:
                        # Directory not empty, stop traversing upwards
                        break
        except Exception as e:
            raise StorageServiceError(
                message="Failed to delete local file",
                details={"key": key, "error": str(e)},
            ) from e

    async def head_object(self, key: str) -> Dict[str, Any]:
        path = self._get_path(key)
        if not path.exists():
            raise StorageServiceError(
                message=f"Object {key} does not exist",
                details={"key": key},
            )
        stat = path.stat()
        return {
            "content_length": stat.st_size,
            "content_type": "application/octet-stream",
            "etag": str(stat.st_mtime),
            "last_modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        }

    async def object_exists(self, key: str) -> bool:
        path = self._get_path(key)
        return path.exists()

    async def copy_object(self, source_key: str, destination_key: str) -> None:
        data = await self.download_bytes(source_key)
        await self.upload_bytes(destination_key, data)

