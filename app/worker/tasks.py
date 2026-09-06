import io
from typing import Any, Dict, Optional
from PIL import Image
from sqlalchemy import select

from app.core.logging import logger
from app.db.session import async_session_factory
from app.models.file import File
from app.storage import get_storage_backend
from app.storage.base import StorageBackend


async def process_file_task(
    payload: Dict[str, Any],
    db: Optional[Any] = None,
    storage: Optional[StorageBackend] = None,
) -> Dict[str, Any]:
    """
    Background worker task:
    1. Downloads file stream from S3 if processing is needed.
    2. Generates thumbnail for image formats using Pillow.
    3. Runs virus scan / integrity verification stub.
    4. Updates File status in DB.
    """
    file_id = payload.get("file_id")
    s3_key = payload.get("s3_key")
    content_type = payload.get("content_type", "")

    logger.info(f"Processing background task for file_id={file_id}, key={s3_key}")

    storage = storage or get_storage_backend()
    thumbnail_key: Optional[str] = None
    status = "READY"

    try:
        # Virus scan stub: check for test signature or invalid bytes
        if s3_key and "eicar" in s3_key.lower():
            status = "INFECTED"
            logger.warning(f"Malware stub detected in file {s3_key}")
        elif content_type.startswith("image/") and s3_key:
            try:
                raw_bytes = await storage.download_bytes(s3_key)
                img = Image.open(io.BytesIO(raw_bytes))
                img.thumbnail((256, 256))
                
                thumb_io = io.BytesIO()
                # Convert RGBA/P to RGB if saving as JPEG or WebP
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                img.save(thumb_io, format="JPEG", quality=85)
                thumb_bytes = thumb_io.getvalue()

                thumbnail_key = f"thumbnails/{file_id}.jpg"
                await storage.upload_bytes(
                    key=thumbnail_key,
                    data=thumb_bytes,
                    content_type="image/jpeg",
                )
                logger.info(f"Generated thumbnail for file {file_id} at {thumbnail_key}")
            except Exception as img_err:
                logger.warning(f"Thumbnail generation failed for {s3_key}: {str(img_err)}")

        # Update DB File status and thumbnail_key
        if file_id:
            if db:
                result = await db.execute(
                    select(File).where(File.id == file_id)
                )
                file_record = result.scalar_one_or_none()
                if file_record:
                    file_record.status = status
                    if thumbnail_key:
                        file_record.thumbnail_s3_key = thumbnail_key
                    await db.commit()
            else:
                async with async_session_factory() as session:
                    result = await session.execute(
                        select(File).where(File.id == file_id)
                    )
                    file_record = result.scalar_one_or_none()
                    if file_record:
                        file_record.status = status
                        if thumbnail_key:
                            file_record.thumbnail_s3_key = thumbnail_key
                        await session.commit()
                        logger.info(f"Updated File {file_id} status to {status}")

        return {
            "file_id": file_id,
            "status": status,
            "thumbnail_key": thumbnail_key,
        }

    except Exception as e:
        logger.error(f"Error in process_file_task for file {file_id}: {str(e)}")
        if file_id:
            try:
                if db:
                    result = await db.execute(
                        select(File).where(File.id == file_id)
                    )
                    file_record = result.scalar_one_or_none()
                    if file_record:
                        file_record.status = "FAILED"
                        await db.commit()
                else:
                    async with async_session_factory() as session:
                        result = await session.execute(
                            select(File).where(File.id == file_id)
                        )
                        file_record = result.scalar_one_or_none()
                        if file_record:
                            file_record.status = "FAILED"
                            await session.commit()
            except Exception:
                pass
        raise


async def purge_retention_task(
    payload: Dict[str, Any],
    db: Optional[Any] = None,
    storage: Optional[StorageBackend] = None,
) -> Dict[str, Any]:
    """Background worker task to purge soft-deleted files past the retention window."""
    from app.services.file_service import FileService

    retention_days = payload.get("retention_days", 14)
    storage = storage or get_storage_backend()

    if db:
        purged = await FileService.purge_expired_files(db, storage, retention_days=retention_days)
    else:
        async with async_session_factory() as session:
            purged = await FileService.purge_expired_files(session, storage, retention_days=retention_days)

    return {"purged_count": purged, "retention_days": retention_days}

