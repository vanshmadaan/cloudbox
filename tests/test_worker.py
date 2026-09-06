import io
import pytest
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.blob import ContentBlob
from app.models.file import File
from app.models.user import User
from app.storage.local import LocalStorageBackend
from app.worker.lambda_handler import handler
from app.worker.tasks import process_file_task


@pytest.mark.asyncio
async def test_worker_task_image_thumbnail_generation(
    db_session: AsyncSession,
    mock_storage: LocalStorageBackend,
):
    # 1. Create a dummy image
    img = Image.new("RGB", (600, 400), color="blue")
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="JPEG")
    img_bytes = img_byte_arr.getvalue()

    s3_key = "blobs/test_img.jpg"
    await mock_storage.upload_bytes(s3_key, img_bytes, "image/jpeg")

    # 2. Insert dummy DB entities
    user = User(
        email="worker_user@example.com",
        hashed_password="pwd",
        storage_quota_bytes=1000000,
        storage_used_bytes=len(img_bytes),
    )
    db_session.add(user)
    await db_session.flush()

    blob = ContentBlob(
        checksum_sha256="test_hash_img",
        s3_key=s3_key,
        byte_size=len(img_bytes),
        content_type="image/jpeg",
        ref_count=1,
    )
    db_session.add(blob)
    await db_session.flush()

    file_obj = File(
        name="photo.jpg",
        owner_id=user.id,
        blob_id=blob.id,
        file_size=len(img_bytes),
        checksum_sha256="test_hash_img",
        status="PENDING",
    )
    db_session.add(file_obj)
    await db_session.commit()

    # 3. Process task
    res = await process_file_task(
        payload={
            "file_id": file_obj.id,
            "s3_key": s3_key,
            "content_type": "image/jpeg",
        },
        db=db_session,
        storage=mock_storage,
    )

    assert res["status"] == "READY"
    assert res["thumbnail_key"] is not None
    # Verify thumbnail exists in storage
    assert await mock_storage.object_exists(res["thumbnail_key"])

