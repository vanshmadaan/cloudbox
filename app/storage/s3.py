import io
from typing import Any, Dict, Optional
import aioboto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.config import settings
from app.core.exceptions import StorageServiceError
from app.core.logging import logger
from app.storage.base import StorageBackend


class S3StorageBackend(StorageBackend):
    """
    AWS S3 Storage implementation using fully async aioboto3.
    """

    def __init__(
        self,
        bucket_name: Optional[str] = None,
        region_name: Optional[str] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        aws_session_token: Optional[str] = None,
        endpoint_url: Optional[str] = None,
    ):
        self.bucket_name = bucket_name or settings.S3_BUCKET_NAME
        self.region_name = region_name or settings.AWS_REGION
        self.aws_access_key_id = aws_access_key_id or settings.AWS_ACCESS_KEY_ID
        self.aws_secret_access_key = aws_secret_access_key or settings.AWS_SECRET_ACCESS_KEY
        self.aws_session_token = aws_session_token or settings.AWS_SESSION_TOKEN
        self.endpoint_url = endpoint_url or settings.S3_ENDPOINT_URL or None

        self.session = aioboto3.Session(
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
            aws_session_token=self.aws_session_token,
            region_name=self.region_name,
        )
        self.boto_config = Config(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"},
        )

    def _get_client(self):
        return self.session.client(
            "s3",
            endpoint_url=self.endpoint_url,
            config=self.boto_config,
        )

    async def generate_presigned_upload_url(
        self,
        key: str,
        content_type: str = "application/octet-stream",
        expires_in: int = 3600,
    ) -> Dict[str, Any]:
        """
        Generate a presigned PUT URL for direct-to-S3 client upload.
        Bypasses Lambda & API Gateway payload limits (e.g. 6MB limit).
        """
        try:
            async with self._get_client() as s3:
                params = {
                    "Bucket": self.bucket_name,
                    "Key": key,
                    "ContentType": content_type,
                }
                url = await s3.generate_presigned_url(
                    ClientMethod="put_object",
                    Params=params,
                    ExpiresIn=expires_in,
                    HttpMethod="PUT",
                )
                return {
                    "method": "PUT",
                    "url": url,
                    "headers": {
                        "Content-Type": content_type,
                    },
                    "key": key,
                    "expires_in": expires_in,
                }
        except Exception as e:
            logger.error(f"Failed to generate presigned upload URL for key {key}: {str(e)}")
            raise StorageServiceError(
                message="Failed to generate presigned upload URL",
                details={"key": key, "error": str(e)},
            ) from e

    async def generate_presigned_download_url(
        self,
        key: str,
        expires_in: int = 3600,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> str:
        """
        Generate a presigned GET URL for direct-from-S3 client download.
        """
        try:
            async with self._get_client() as s3:
                params: Dict[str, Any] = {
                    "Bucket": self.bucket_name,
                    "Key": key,
                }
                if filename:
                    # RFC 5987 / 6266 safe header encoding guaranteed to be valid ASCII / ISO-8859-1 for AWS S3
                    import unicodedata
                    from urllib.parse import quote

                    normalized = unicodedata.normalize("NFKD", filename)
                    ascii_clean = (
                        normalized.encode("ascii", "ignore")
                        .decode("ascii")
                        .replace('"', '\\"')
                        .strip()
                    )
                    if not ascii_clean:
                        ext = filename.split(".")[-1] if "." in filename else ""
                        ascii_clean = f"download.{ext}" if ext else "download"

                    encoded_filename = quote(filename, encoding="utf-8")
                    params["ResponseContentDisposition"] = (
                        f'attachment; filename="{ascii_clean}"; filename*=UTF-8\'\'{encoded_filename}'
                    )
                if content_type:
                    params["ResponseContentType"] = content_type
                params["ResponseCacheControl"] = "public, max-age=86400"
                url = await s3.generate_presigned_url(
                    ClientMethod="get_object",
                    Params=params,
                    ExpiresIn=expires_in,
                    HttpMethod="GET",
                )
                return url
        except Exception as e:
            logger.error(f"Failed to generate presigned download URL for key {key}: {str(e)}")
            raise StorageServiceError(
                message="Failed to generate presigned download URL",
                details={"key": key, "error": str(e)},
            ) from e

    async def upload_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> None:
        try:
            async with self._get_client() as s3:
                await s3.put_object(
                    Bucket=self.bucket_name,
                    Key=key,
                    Body=data,
                    ContentType=content_type,
                )
        except Exception as e:
            logger.error(f"Failed to upload bytes to S3 key {key}: {str(e)}")
            raise StorageServiceError(
                message="Failed to upload file to storage",
                details={"key": key, "error": str(e)},
            ) from e

    async def download_bytes(self, key: str) -> bytes:
        try:
            async with self._get_client() as s3:
                response = await s3.get_object(Bucket=self.bucket_name, Key=key)
                async with response["Body"] as stream:
                    return await stream.read()
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "NoSuchKey":
                raise StorageServiceError(
                    message=f"Object not found in storage: {key}",
                    details={"key": key},
                )
            raise StorageServiceError(
                message="Failed to download file from storage",
                details={"key": key, "error": str(e)},
            ) from e
        except Exception as e:
            logger.error(f"Failed to download bytes from S3 key {key}: {str(e)}")
            raise StorageServiceError(
                message="Failed to download file from storage",
                details={"key": key, "error": str(e)},
            ) from e

    async def delete_object(self, key: str) -> None:
        try:
            async with self._get_client() as s3:
                await s3.delete_object(Bucket=self.bucket_name, Key=key)
        except Exception as e:
            logger.error(f"Failed to delete S3 key {key}: {str(e)}")
            raise StorageServiceError(
                message="Failed to delete object from storage",
                details={"key": key, "error": str(e)},
            ) from e

    async def head_object(self, key: str) -> Dict[str, Any]:
        try:
            async with self._get_client() as s3:
                response = await s3.head_object(Bucket=self.bucket_name, Key=key)
                return {
                    "content_length": response.get("ContentLength", 0),
                    "content_type": response.get("ContentType", "application/octet-stream"),
                    "etag": response.get("ETag", "").strip('"'),
                    "last_modified": response.get("LastModified"),
                }
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ["404", "NoSuchKey"]:
                raise StorageServiceError(
                    message=f"Object {key} does not exist in storage",
                    details={"key": key},
                )
            raise StorageServiceError(
                message=f"Failed to head object {key}",
                details={"key": key, "error": str(e)},
            ) from e
        except Exception as e:
            raise StorageServiceError(
                message=f"Failed to head object {key}",
                details={"key": key, "error": str(e)},
            ) from e

    async def object_exists(self, key: str) -> bool:
        try:
            async with self._get_client() as s3:
                await s3.head_object(Bucket=self.bucket_name, Key=key)
                return True
        except Exception:
            return False

    async def copy_object(self, source_key: str, destination_key: str) -> None:
        try:
            async with self._get_client() as s3:
                copy_source = {"Bucket": self.bucket_name, "Key": source_key}
                await s3.copy_object(
                    Bucket=self.bucket_name,
                    Key=destination_key,
                    CopySource=copy_source,
                )
        except Exception as e:
            logger.error(f"Failed to copy S3 object from {source_key} to {destination_key}: {str(e)}")
            raise StorageServiceError(
                message="Failed to copy object in storage",
                details={"source": source_key, "destination": destination_key, "error": str(e)},
            ) from e

