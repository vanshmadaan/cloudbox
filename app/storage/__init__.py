from app.core.config import settings
from app.storage.base import StorageBackend
from app.storage.local import LocalStorageBackend
from app.storage.s3 import S3StorageBackend


def get_storage_backend() -> StorageBackend:
    """Factory creating configured StorageBackend instance."""
    if settings.STORAGE_BACKEND.lower() == "local":
        return LocalStorageBackend()

    # If S3 is requested without credentials or endpoint in local development, fall back to local storage
    if (
        settings.ENVIRONMENT == "development"
        and not settings.AWS_ACCESS_KEY_ID
        and not settings.S3_ENDPOINT_URL
    ):
        return LocalStorageBackend()

    return S3StorageBackend()


__all__ = [
    "StorageBackend",
    "S3StorageBackend",
    "LocalStorageBackend",
    "get_storage_backend",
]

