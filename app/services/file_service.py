import asyncio
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    QuotaExceededError,
    ValidationError,
)
from app.core.logging import logger
from app.models.blob import ContentBlob
from app.models.file import File
from app.models.folder import Folder
from app.models.user import User
from app.schemas.file import (
    CompleteUploadRequest,
    FileDetailResponse,
    FileDownloadResponse,
    FilePreviewResponse,
    FileResponse,
    FileUpdate,
    PresignedUploadRequest,
    PresignedUploadResponse,
    TrashFileResponse,
)
from app.services.folder_service import FolderService
from app.services.queue_service import QueueService
from app.storage.base import StorageBackend


class FileService:
    """Business logic for file metadata, uploads, downloads, and lifecycle."""

    @staticmethod
    async def request_presigned_upload(
        db: AsyncSession,
        user: User,
        upload_req: PresignedUploadRequest,
        storage: StorageBackend,
    ) -> PresignedUploadResponse:
        # 1. Quota Pre-check
        user_res = await db.execute(select(User).where(User.id == user.id))
        current_user = user_res.scalar_one()

        if current_user.storage_used_bytes + upload_req.file_size > current_user.storage_quota_bytes:
            raise QuotaExceededError(
                used_bytes=current_user.storage_used_bytes,
                quota_bytes=current_user.storage_quota_bytes,
                requested_bytes=upload_req.file_size,
            )

        # 2. Verify folder exists if specified and is not in trash
        if upload_req.folder_id:
            folder_res = await db.execute(
                select(Folder).where(
                    Folder.id == upload_req.folder_id,
                    Folder.owner_id == user.id,
                    Folder.is_deleted.is_(False),
                )
            )
            if not folder_res.scalar_one_or_none() or await FolderService.is_folder_in_trash(db, upload_req.folder_id):
                raise NotFoundError("Folder", upload_req.folder_id)

        # 3. Generate unique temporary key for raw upload
        temp_key = f"tmp-uploads/{user.id}/{uuid.uuid4()}/{upload_req.name}"

        # 4. Generate presigned PUT URL
        presigned = await storage.generate_presigned_upload_url(
            key=temp_key,
            content_type=upload_req.content_type,
            expires_in=3600,
        )

        return PresignedUploadResponse(
            upload_url=presigned["url"],
            http_method=presigned.get("method", "PUT"),
            headers=presigned.get("headers", {}),
            temp_s3_key=temp_key,
            file_id=upload_req.file_id,
            expires_in=3600,
        )

    @staticmethod
    async def _generate_unique_filename(
        db: AsyncSession,
        owner_id: str,
        folder_id: Optional[str],
        original_name: str,
    ) -> str:
        """Generate a non-conflicting filename if a file with the same name already exists."""
        q = select(File.id).where(
            File.owner_id == owner_id,
            File.name == original_name,
            File.is_deleted.is_(False),
        )
        if folder_id:
            q = q.where(File.folder_id == folder_id)
        else:
            q = q.where(File.folder_id.is_(None))

        exists = (await db.execute(q)).scalar_one_or_none()
        if not exists:
            return original_name

        if "." in original_name and not original_name.startswith("."):
            base_name, ext = original_name.rsplit(".", 1)
            ext = f".{ext}"
        else:
            base_name, ext = original_name, ""

        counter = 1
        while True:
            candidate = f"{base_name} ({counter}){ext}"
            q_candidate = select(File.id).where(
                File.owner_id == owner_id,
                File.name == candidate,
                File.is_deleted.is_(False),
            )
            if folder_id:
                q_candidate = q_candidate.where(File.folder_id == folder_id)
            else:
                q_candidate = q_candidate.where(File.folder_id.is_(None))
            if not (await db.execute(q_candidate)).scalar_one_or_none():
                return candidate
            counter += 1

    @staticmethod
    async def complete_upload(
        db: AsyncSession,
        user: User,
        complete_req: CompleteUploadRequest,
        storage: StorageBackend,
        queue_service: QueueService,
    ) -> FileResponse:
        # 1. Refresh & verify user quota
        user_res = await db.execute(select(User).where(User.id == user.id))
        current_user = user_res.scalar_one()

        if current_user.storage_used_bytes + complete_req.file_size > current_user.storage_quota_bytes:
            raise QuotaExceededError(
                used_bytes=current_user.storage_used_bytes,
                quota_bytes=current_user.storage_quota_bytes,
                requested_bytes=complete_req.file_size,
            )

        # Verify target folder is not in trash
        if complete_req.folder_id:
            folder_res = await db.execute(
                select(Folder).where(
                    Folder.id == complete_req.folder_id,
                    Folder.owner_id == user.id,
                    Folder.is_deleted.is_(False),
                )
            )
            if not folder_res.scalar_one_or_none() or await FolderService.is_folder_in_trash(db, complete_req.folder_id):
                raise NotFoundError("Folder", complete_req.folder_id)

        sha256 = complete_req.checksum_sha256.lower()

        # 2. Deduplication check: see if content blob already exists
        blob_res = await db.execute(
            select(ContentBlob).where(ContentBlob.checksum_sha256 == sha256)
        )
        blob = blob_res.scalar_one_or_none()
        is_existing_blob = False
        if blob:
            is_existing_blob = True
            logger.info(f"Deduplication hit for SHA-256 {sha256}. Reusing blob {blob.id}")
            try:
                await storage.delete_object(complete_req.temp_s3_key)
            except Exception as e:
                logger.warning(f"Could not delete temp key {complete_req.temp_s3_key}: {e}")
        else:
            # New unique content: move/copy from temp location to permanent blob key
            perm_key = f"blobs/{sha256[:2]}/{sha256[2:4]}/{sha256}"
            try:
                await storage.copy_object(
                    source_key=complete_req.temp_s3_key,
                    destination_key=perm_key,
                )
                await storage.delete_object(complete_req.temp_s3_key)
            except Exception as e:
                logger.error(f"Failed moving S3 object from {complete_req.temp_s3_key} to {perm_key}: {e}")
                # Fallback: keep temp key if copy failed
                perm_key = complete_req.temp_s3_key

            blob = ContentBlob(
                checksum_sha256=sha256,
                s3_key=perm_key,
                byte_size=complete_req.file_size,
                content_type=complete_req.content_type,
                ref_count=1,
            )
            db.add(blob)
            await db.flush()

        # 3. Determine if this is a new file or overwriting an existing file
        file_obj: Optional[File] = None
        if complete_req.file_id:
            f_res = await db.execute(
                select(File).where(File.id == complete_req.file_id, File.owner_id == user.id)
            )
            file_obj = f_res.scalar_one_or_none()

        if file_obj:
            # Overwrite existing file:
            old_size = file_obj.file_size
            old_blob = file_obj.blob
            # If pointing to a different blob, adjust ref_counts
            if old_blob and old_blob.id != blob.id:
                blob.ref_count += 1
                old_blob.ref_count -= 1
                if old_blob.ref_count <= 0:
                    try:
                        await storage.delete_object(old_blob.s3_key)
                    except Exception as e:
                        logger.warning(f"Failed to delete unreferenced blob {old_blob.s3_key}: {e}")
                    await db.delete(old_blob)

            # Reassign file entity to new blob
            file_obj.blob = blob
            file_obj.blob_id = blob.id
            file_obj.file_size = complete_req.file_size
            file_obj.checksum_sha256 = sha256
            file_obj.status = "PENDING"

            # Update user quota difference
            current_user.storage_used_bytes = max(0, current_user.storage_used_bytes - old_size + complete_req.file_size)
        else:
            # Brand new file entity: auto-rename if duplicate exists
            unique_filename = await FileService._generate_unique_filename(
                db=db,
                owner_id=user.id,
                folder_id=complete_req.folder_id,
                original_name=complete_req.name,
            )

            if is_existing_blob:
                blob.ref_count += 1

            file_obj = File(
                name=unique_filename,
                folder_id=complete_req.folder_id,
                owner_id=user.id,
                blob_id=blob.id,
                file_size=complete_req.file_size,
                checksum_sha256=sha256,
                status="PENDING",
            )
            db.add(file_obj)
            current_user.storage_used_bytes += complete_req.file_size

        await db.commit()
        await db.refresh(file_obj)

        # 5. Dispatch async background task to SQS (thumbnails, scan)
        await queue_service.enqueue_task(
            task_type="process_file",
            payload={
                "file_id": file_obj.id,
                "blob_id": blob.id,
                "s3_key": blob.s3_key,
                "content_type": complete_req.content_type,
            },
        )

        return await FileService._to_file_response(db, file_obj, storage)

    @staticmethod
    async def upload_direct(
        db: AsyncSession,
        user: User,
        filename: str,
        content: bytes,
        content_type: str,
        folder_id: Optional[str],
        storage: StorageBackend,
        queue_service: QueueService,
        file_id: Optional[str] = None,
    ) -> FileResponse:
        """Direct upload method for small files, multipart form uploads, or testing."""
        file_size = len(content)
        sha256 = hashlib.sha256(content).hexdigest()

        # Temporary key upload
        temp_key = f"tmp-direct/{user.id}/{uuid.uuid4()}/{filename}"
        await storage.upload_bytes(temp_key, content, content_type)

        complete_req = CompleteUploadRequest(
            temp_s3_key=temp_key,
            name=filename,
            file_size=file_size,
            checksum_sha256=sha256,
            folder_id=folder_id,
            content_type=content_type,
            file_id=file_id,
        )

        return await FileService.complete_upload(
            db=db,
            user=user,
            complete_req=complete_req,
            storage=storage,
            queue_service=queue_service,
        )

    @staticmethod
    async def get_file(
        db: AsyncSession,
        file_id: str,
        owner_id: str,
        storage: StorageBackend,
    ) -> FileDetailResponse:
        file_obj = await FileService._get_file_entity(db, file_id, owner_id)
        base_resp = await FileService._to_file_response(db, file_obj, storage)
        return FileDetailResponse(**base_resp.model_dump())

    @staticmethod
    def _matches_file_type(name: str, content_type: Optional[str], file_type: str) -> bool:
        ft = file_type.lower().strip()
        name_lower = name.lower()
        ct_lower = (content_type or "").lower()

        if ft == "image":
            return ct_lower.startswith("image/") or name_lower.endswith(
                (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico")
            )
        elif ft == "video":
            return ct_lower.startswith("video/") or name_lower.endswith(
                (".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv")
            )
        elif ft == "audio":
            return ct_lower.startswith("audio/") or name_lower.endswith(
                (".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac")
            )
        elif ft in ("document", "documents", "doc"):
            return (
                ct_lower.startswith("text/")
                or "pdf" in ct_lower
                or "officedocument" in ct_lower
                or "msword" in ct_lower
                or name_lower.endswith(
                    (".pdf", ".doc", ".docx", ".txt", ".csv", ".xlsx", ".xls", ".pptx", ".ppt", ".md", ".rtf", ".json", ".xml")
                )
            )
        elif ft in ("archive", "archives", "zip"):
            return (
                "zip" in ct_lower
                or "tar" in ct_lower
                or "compressed" in ct_lower
                or name_lower.endswith((".zip", ".tar", ".gz", ".rar", ".7z", ".bz2", ".xz"))
            )
        else:
            return ft in ct_lower or name_lower.endswith(f".{ft}")

    @staticmethod
    async def list_files(
        db: AsyncSession,
        owner_id: str,
        folder_id: Optional[str] = None,
        search: Optional[str] = None,
        file_type: Optional[str] = None,
        sort_by: str = "created_at",
        order: str = "desc",
        storage: Optional[StorageBackend] = None,
    ) -> List[FileResponse]:
        if folder_id and await FolderService.is_folder_in_trash(db, folder_id):
            return []

        query = select(File).where(
            File.owner_id == owner_id,
            File.is_deleted.is_(False),
        )
        if folder_id:
            query = query.where(File.folder_id == folder_id)
        elif not search:
            query = query.where(File.folder_id.is_(None))

        if search and search.strip():
            query = query.where(File.name.ilike(f"%{search.strip()}%"))

        sort_col = File.created_at
        if sort_by == "name":
            sort_col = File.name
        elif sort_by in ("size", "file_size"):
            sort_col = File.file_size
        elif sort_by == "updated_at":
            sort_col = File.updated_at
        elif sort_by == "deleted_at":
            sort_col = File.deleted_at

        if order and order.lower() == "asc":
            query = query.order_by(sort_col.asc())
        else:
            query = query.order_by(sort_col.desc())

        result = await db.execute(query)
        files = list(result.scalars().all())

        # Filter out files whose parent folder is in trash (with memoization)
        active_files = []
        trash_cache: Dict[str, bool] = {}
        for f in files:
            if folder_id:
                # folder_id was already verified not in trash at line 371
                is_trash = False
            elif not f.folder_id:
                is_trash = False
            else:
                if f.folder_id not in trash_cache:
                    trash_cache[f.folder_id] = await FolderService.is_folder_in_trash(db, f.folder_id)
                is_trash = trash_cache[f.folder_id]

            if not is_trash:
                if file_type and file_type.strip():
                    blob = f.blob
                    ct = blob.content_type if blob else None
                    if not FileService._matches_file_type(f.name, ct, file_type):
                        continue
                active_files.append(f)

        responses = await asyncio.gather(
            *[FileService._to_file_response(db, f, storage, include_download_urls=False) for f in active_files]
        )
        return list(responses)

    @staticmethod
    async def get_download_url(
        db: AsyncSession,
        file_id: str,
        owner_id: str,
        storage: StorageBackend,
    ) -> FileDownloadResponse:
        file_obj = await FileService._get_file_entity(db, file_id, owner_id)
        blob = file_obj.blob
        if not blob:
            raise NotFoundError("ContentBlob", file_id)

        download_url = await storage.generate_presigned_download_url(
            key=blob.s3_key,
            expires_in=3600,
            filename=file_obj.name,
            content_type=blob.content_type,
        )

        return FileDownloadResponse(
            download_url=download_url,
            filename=file_obj.name,
            file_size=file_obj.file_size,
            content_type=blob.content_type,
            expires_in=3600,
        )

    @staticmethod
    async def get_preview_url(
        db: AsyncSession,
        file_id: str,
        owner_id: str,
        storage: StorageBackend,
    ) -> FilePreviewResponse:
        file_obj = await FileService._get_file_entity(db, file_id, owner_id)
        blob = file_obj.blob
        if not blob:
            raise NotFoundError("ContentBlob", file_id)

        preview_url = await storage.generate_presigned_download_url(
            key=blob.s3_key,
            expires_in=3600,
            filename=None,
            content_type=blob.content_type,
        )
        download_url = await storage.generate_presigned_download_url(
            key=blob.s3_key,
            expires_in=3600,
            filename=file_obj.name,
            content_type=blob.content_type,
        )

        return FilePreviewResponse(
            file_id=file_obj.id,
            filename=file_obj.name,
            file_size=file_obj.file_size,
            content_type=blob.content_type,
            preview_url=preview_url,
            download_url=download_url,
            expires_in=3600,
        )

    @staticmethod
    async def update_file(
        db: AsyncSession,
        file_id: str,
        owner_id: str,
        file_in: FileUpdate,
        storage: StorageBackend,
    ) -> FileResponse:
        file_obj = await FileService._get_file_entity(db, file_id, owner_id)

        new_name = file_in.name if file_in.name is not None else file_obj.name
        new_folder_id = file_obj.folder_id

        if "folder_id" in file_in.model_fields_set:
            target_folder_id = None if file_in.folder_id in (None, "", "root") else file_in.folder_id
            if target_folder_id is not None:
                # Verify folder exists, belongs to owner, and is not in trash
                f_res = await db.execute(
                    select(Folder).where(
                        Folder.id == target_folder_id,
                        Folder.owner_id == owner_id,
                    )
                )
                target_folder = f_res.scalar_one_or_none()
                if not target_folder or target_folder.is_deleted or await FolderService.is_folder_in_trash(db, target_folder_id):
                    raise NotFoundError("Folder", target_folder_id)
            new_folder_id = target_folder_id

        # Validate duplicate name if name or folder changed
        if new_name != file_obj.name or new_folder_id != file_obj.folder_id:
            folder_filter = File.folder_id.is_(None) if new_folder_id is None else (File.folder_id == new_folder_id)
            q = select(File).where(
                File.owner_id == owner_id,
                folder_filter,
                File.name == new_name,
                File.id != file_id,
                File.is_deleted.is_(False),
            )
            if (await db.execute(q)).scalar_one_or_none():
                loc_desc = "Home" if new_folder_id is None else "this folder"
                raise ValidationError(f"File with name '{new_name}' already exists in {loc_desc}")

        file_obj.name = new_name
        file_obj.folder_id = new_folder_id
        file_obj.updated_at = datetime.now(timezone.utc)

        await db.commit()
        await db.refresh(file_obj)
        return await FileService._to_file_response(db, file_obj, storage)

    @staticmethod
    async def delete_file(
        db: AsyncSession,
        file_id: str,
        owner_id: str,
        storage: Optional[StorageBackend] = None,
    ) -> None:
        """
        Soft-delete file:
        1. Sets is_deleted = True and deleted_at = UTC NOW.
        2. Deactivates all associated SharedLinks.
        3. Frees the user's active storage quota.
        4. Retains metadata and S3 storage objects for 14 days before permanent purge.
        """
        file_obj = await FileService._get_file_entity(db, file_id, owner_id)

        # 1. Soft-delete flags
        file_obj.is_deleted = True
        file_obj.deleted_at = datetime.now(timezone.utc)

        # 2. Deactivate active share links
        for share in file_obj.shared_links:
            share.is_active = False

        # 3. Refund user active storage quota
        user_res = await db.execute(select(User).where(User.id == owner_id))
        user = user_res.scalar_one()
        user.storage_used_bytes = max(0, user.storage_used_bytes - file_obj.file_size)

        await db.commit()
        logger.info(f"File {file_id} ('{file_obj.name}') soft-deleted for user {owner_id}. Retained for 14 days.")

    @staticmethod
    async def list_trash_files(
        db: AsyncSession,
        owner_id: str,
        search: Optional[str] = None,
        file_type: Optional[str] = None,
        sort_by: str = "deleted_at",
        order: str = "desc",
    ) -> List[TrashFileResponse]:
        """List all soft-deleted files currently in trash for the user."""
        query = (
            select(File)
            .where(
                File.owner_id == owner_id,
                File.is_deleted.is_(True),
            )
        )
        if search and search.strip():
            query = query.where(File.name.ilike(f"%{search.strip()}%"))

        sort_col = File.deleted_at
        if sort_by == "name":
            sort_col = File.name
        elif sort_by in ("size", "file_size"):
            sort_col = File.file_size
        elif sort_by == "created_at":
            sort_col = File.created_at

        if order and order.lower() == "asc":
            query = query.order_by(sort_col.asc())
        else:
            query = query.order_by(sort_col.desc())

        result = await db.execute(query)
        files = list(result.scalars().all())

        responses: List[TrashFileResponse] = []
        for f in files:
            blob = f.blob
            c_type = blob.content_type if blob else "application/octet-stream"
            if file_type and file_type.strip():
                if not FileService._matches_file_type(f.name, c_type, file_type):
                    continue
            responses.append(
                TrashFileResponse(
                    id=f.id,
                    name=f.name,
                    folder_id=f.folder_id,
                    file_size=f.file_size,
                    content_type=c_type,
                    deleted_at=f.deleted_at or f.created_at,
                    days_until_purge=f.days_until_purge(retention_days=14),
                    created_at=f.created_at,
                )
            )
        return responses

    @staticmethod
    async def restore_file(
        db: AsyncSession,
        file_id: str,
        owner_id: str,
        storage: StorageBackend,
    ) -> FileResponse:
        """Restore a soft-deleted file from trash back to active status."""
        query = select(File).where(
            File.id == file_id,
            File.owner_id == owner_id,
            File.is_deleted.is_(True),
        )
        result = await db.execute(query)
        file_obj = result.scalar_one_or_none()
        if not file_obj:
            raise NotFoundError("Deleted file", file_id)

        # Check user quota availability
        user_res = await db.execute(select(User).where(User.id == owner_id))
        user = user_res.scalar_one()

        if user.storage_used_bytes + file_obj.file_size > user.storage_quota_bytes:
            raise QuotaExceededError(
                used_bytes=user.storage_used_bytes,
                quota_bytes=user.storage_quota_bytes,
                requested_bytes=file_obj.file_size,
            )

        # Check if parent folder still exists and is not in trash; if not, restore to root
        if file_obj.folder_id:
            folder_res = await db.execute(
                select(Folder).where(
                    Folder.id == file_obj.folder_id,
                    Folder.owner_id == owner_id,
                    Folder.is_deleted.is_(False),
                )
            )
            if not folder_res.scalar_one_or_none() or await FolderService.is_folder_in_trash(db, file_obj.folder_id):
                file_obj.folder_id = None

        # Check for name conflict with active file in destination
        folder_filter = File.folder_id.is_(None) if file_obj.folder_id is None else (File.folder_id == file_obj.folder_id)
        dup_q = select(File).where(
            File.owner_id == owner_id,
            folder_filter,
            File.name == file_obj.name,
            File.id != file_obj.id,
            File.is_deleted.is_(False),
        )
        if (await db.execute(dup_q)).scalar_one_or_none():
            loc_desc = "Home" if file_obj.folder_id is None else "the destination folder"
            raise ConflictError(
                message=f"A file with name '{file_obj.name}' already exists in {loc_desc}. Please rename or delete the existing file first.",
                code="FILE_ALREADY_EXISTS",
            )

        # Restore file state
        file_obj.is_deleted = False
        file_obj.deleted_at = None
        user.storage_used_bytes += file_obj.file_size

        # Reactivate unexpired share links for this restored file
        for share in file_obj.shared_links:
            if not share.is_expired:
                share.is_active = True

        await db.commit()
        await db.refresh(file_obj)
        logger.info(f"File {file_id} ('{file_obj.name}') restored from trash for user {owner_id}, share links reactivated.")
        return await FileService._to_file_response(db, file_obj, storage)

    @staticmethod
    async def permanent_delete_file(
        db: AsyncSession,
        file_id: str,
        owner_id: str,
        storage: StorageBackend,
    ) -> None:
        """Permanently delete a file, delete associated share link records, decrement blob reference count, and purge S3 bytes."""
        query = select(File).where(
            File.id == file_id,
            File.owner_id == owner_id,
        )
        result = await db.execute(query)
        file_obj = result.scalar_one_or_none()
        if not file_obj:
            raise NotFoundError("File", file_id)

        # If file was active (not soft deleted), decrement quota
        if not file_obj.is_deleted:
            user_res = await db.execute(select(User).where(User.id == owner_id))
            user = user_res.scalar_one()
            user.storage_used_bytes = max(0, user.storage_used_bytes - file_obj.file_size)

        # Explicitly remove all associated share link records from database
        for share in list(file_obj.shared_links):
            await db.delete(share)

        # Collect blobs to prune if ref_count drops to <= 0
        blobs_to_delete = []
        blob = file_obj.blob
        if blob:
            blob.ref_count -= 1
            if blob.ref_count <= 0:
                try:
                    await storage.delete_object(blob.s3_key)
                except Exception as e:
                    logger.warning(f"Failed to delete unreferenced S3 blob {blob.s3_key}: {e}")
                blobs_to_delete.append(blob)
        if file_obj.thumbnail_s3_key:
            try:
                await storage.delete_object(file_obj.thumbnail_s3_key)
            except Exception as e:
                logger.warning(f"Failed to delete thumbnail {file_obj.thumbnail_s3_key}: {e}")

        # Delete File entity
        await db.delete(file_obj)
        await db.flush()

        # Delete unreferenced ContentBlobs from database
        for b in blobs_to_delete:
            await db.delete(b)

        await db.commit()
        logger.info(f"File {file_id} and associated blobs/shares permanently purged from database and storage.")

    @staticmethod
    async def purge_expired_files(
        db: AsyncSession,
        storage: StorageBackend,
        retention_days: int = 14,
    ) -> int:
        """
        Background maintenance job:
        Finds all folders and files soft-deleted >= retention_days ago, removes share links/blobs, and permanently deletes them.
        """
        # 1. Purge expired folders (and their contents)
        folders_purged = await FolderService.purge_expired_folders(
            db=db,
            storage=storage,
            retention_days=retention_days,
        )

        # 2. Purge standalone expired files
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)
        query = select(File).where(
            File.is_deleted.is_(True),
            File.deleted_at <= cutoff_date,
        )
        result = await db.execute(query)
        expired_files = list(result.scalars().all())

        purged_count = 0
        for file_obj in expired_files:
            # Explicitly remove associated share links
            for share in list(file_obj.shared_links):
                await db.delete(share)

            blobs_to_delete = []
            blob = file_obj.blob
            if blob:
                blob.ref_count -= 1
                if blob.ref_count <= 0:
                    try:
                        await storage.delete_object(blob.s3_key)
                    except Exception as e:
                        logger.warning(f"Failed to delete expired blob {blob.s3_key}: {e}")
                    blobs_to_delete.append(blob)
            if file_obj.thumbnail_s3_key:
                try:
                    await storage.delete_object(file_obj.thumbnail_s3_key)
                except Exception as e:
                    logger.warning(f"Failed to delete expired thumbnail {file_obj.thumbnail_s3_key}: {e}")

            await db.delete(file_obj)
            await db.flush()

            for b in blobs_to_delete:
                await db.delete(b)

            purged_count += 1

        if purged_count > 0 or folders_purged > 0:
            await db.commit()
            logger.info(f"Purged {folders_purged} folders and {purged_count} standalone files past {retention_days}-day retention window.")

        return purged_count + folders_purged

    @staticmethod
    async def _get_file_entity(db: AsyncSession, file_id: str, owner_id: str) -> File:
        result = await db.execute(
            select(File).where(
                File.id == file_id,
                File.owner_id == owner_id,
                File.is_deleted.is_(False),
            )
        )
        file_obj = result.scalar_one_or_none()
        if not file_obj:
            raise NotFoundError("File", file_id)
        if file_obj.folder_id and await FolderService.is_folder_in_trash(db, file_obj.folder_id):
            raise NotFoundError("File", file_id)
        return file_obj

    @staticmethod
    async def _to_file_response(
        db: AsyncSession,
        file_obj: File,
        storage: Optional[StorageBackend] = None,
        include_download_urls: bool = True,
    ) -> FileResponse:
        blob = file_obj.blob
        file_size = file_obj.file_size
        content_type = blob.content_type if blob else "application/octet-stream"
        status = file_obj.status
        checksum = file_obj.checksum_sha256

        download_url = None
        preview_url = None
        thumbnail_url = None
        if storage and blob:
            try:
                if include_download_urls:
                    download_url = await storage.generate_presigned_download_url(
                        key=blob.s3_key,
                        expires_in=3600,
                        filename=file_obj.name,
                        content_type=content_type,
                    )
                    preview_url = await storage.generate_presigned_download_url(
                        key=blob.s3_key,
                        expires_in=3600,
                        filename=None,
                        content_type=content_type,
                    )
                if file_obj.thumbnail_s3_key:
                    thumbnail_url = await storage.generate_presigned_download_url(
                        key=file_obj.thumbnail_s3_key,
                        expires_in=3600,
                    )
            except Exception:
                pass

        return FileResponse(
            id=file_obj.id,
            name=file_obj.name,
            folder_id=file_obj.folder_id,
            owner_id=file_obj.owner_id,
            file_size=file_size,
            content_type=content_type,
            status=status,
            checksum_sha256=checksum,
            download_url=download_url,
            thumbnail_url=thumbnail_url,
            preview_url=preview_url,
            is_deleted=file_obj.is_deleted,
            created_at=file_obj.created_at,
            updated_at=file_obj.updated_at,
        )

    @staticmethod
    async def empty_trash(
        db: AsyncSession,
        owner_id: str,
        storage: StorageBackend,
    ) -> Tuple[int, int]:
        """
        Permanently delete all folders and files in trash for this user forever.
        Returns (folders_purged_count, files_purged_count).
        """
        # 1. Find all soft-deleted folders for this user
        f_query = select(Folder.id).where(
            Folder.owner_id == owner_id,
            Folder.is_deleted.is_(True),
        )
        f_res = await db.execute(f_query)
        trash_folder_ids = list(f_res.scalars().all())

        folders_purged = 0
        for folder_id in trash_folder_ids:
            try:
                await FolderService.permanent_delete_folder(
                    db=db,
                    folder_id=folder_id,
                    owner_id=owner_id,
                    storage=storage,
                )
                folders_purged += 1
            except Exception as e:
                logger.warning(f"Failed to permanently delete folder {folder_id} during empty_trash: {e}")

        # 2. Find all remaining soft-deleted standalone files for this user
        file_query = select(File.id).where(
            File.owner_id == owner_id,
            File.is_deleted.is_(True),
        )
        file_res = await db.execute(file_query)
        trash_file_ids = list(file_res.scalars().all())

        files_purged = 0
        for file_id in trash_file_ids:
            try:
                await FileService.permanent_delete_file(
                    db=db,
                    file_id=file_id,
                    owner_id=owner_id,
                    storage=storage,
                )
                files_purged += 1
            except Exception as e:
                logger.warning(f"Failed to permanently delete file {file_id} during empty_trash: {e}")

        logger.info(f"Emptied trash for user {owner_id}: {folders_purged} folders and {files_purged} files purged forever.")
        return folders_purged, files_purged

    @staticmethod
    async def restore_all_trash(
        db: AsyncSession,
        owner_id: str,
        storage: StorageBackend,
    ) -> Tuple[int, int]:
        """
        Restore all folders and files currently in trash back to active directory for this user.
        Returns (folders_restored_count, files_restored_count).
        """
        # 1. Restore all soft-deleted folders
        f_query = select(Folder.id).where(
            Folder.owner_id == owner_id,
            Folder.is_deleted.is_(True),
        )
        f_res = await db.execute(f_query)
        trash_folder_ids = list(f_res.scalars().all())

        folders_restored = 0
        for folder_id in trash_folder_ids:
            try:
                await FolderService.restore_folder(
                    db=db,
                    folder_id=folder_id,
                    owner_id=owner_id,
                )
                folders_restored += 1
            except Exception as e:
                logger.warning(f"Failed to restore folder {folder_id} during restore_all_trash: {e}")

        # 2. Restore all soft-deleted files
        file_query = select(File.id).where(
            File.owner_id == owner_id,
            File.is_deleted.is_(True),
        )
        file_res = await db.execute(file_query)
        trash_file_ids = list(file_res.scalars().all())

        files_restored = 0
        for file_id in trash_file_ids:
            try:
                await FileService.restore_file(
                    db=db,
                    file_id=file_id,
                    owner_id=owner_id,
                    storage=storage,
                )
                files_restored += 1
            except Exception as e:
                logger.warning(f"Failed to restore file {file_id} during restore_all_trash: {e}")

        logger.info(f"Restored all trash for user {owner_id}: {folders_restored} folders and {files_restored} files restored.")
        return folders_restored, files_restored

