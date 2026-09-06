import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("cloud_storage")

from app.core.exceptions import (
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.core.security import generate_share_token
from app.models.file import File
from app.models.folder import Folder
from app.models.share import SharedLink
from app.schemas.share import PublicShareAccessResponse, ShareCreate, ShareResponse
from app.services.folder_service import FolderService
from app.storage.base import StorageBackend


class ShareService:
    """Business logic for public/private shareable links and permissions."""

    @staticmethod
    async def create_share_link(
        db: AsyncSession,
        owner_id: str,
        share_in: ShareCreate,
    ) -> ShareResponse:
        if not share_in.file_id and not share_in.folder_id:
            raise ValidationError("Must provide either file_id or folder_id to share")

        item_name = "Shared Item"
        target_folder_id = share_in.folder_id

        if share_in.file_id:
            f_res = await db.execute(
                select(File).where(File.id == share_in.file_id, File.owner_id == owner_id, File.is_deleted.is_(False))
            )
            file_obj = f_res.scalar_one_or_none()
            if not file_obj or (file_obj.folder_id and await FolderService.is_folder_in_trash(db, file_obj.folder_id)):
                raise NotFoundError("File", share_in.file_id)
            item_name = file_obj.name
            target_folder_id = file_obj.folder_id

        if share_in.folder_id:
            f_res = await db.execute(
                select(Folder).where(Folder.id == share_in.folder_id, Folder.owner_id == owner_id, Folder.is_deleted.is_(False))
            )
            folder_obj = f_res.scalar_one_or_none()
            if not folder_obj or await FolderService.is_folder_in_trash(db, folder_obj.id):
                raise NotFoundError("Folder", share_in.folder_id)
            item_name = folder_obj.name
            target_folder_id = folder_obj.id

        expires_at = None
        if share_in.expires_at:
            expires_at = share_in.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= datetime.now(timezone.utc):
                raise ValidationError("Expiration timestamp must be in the future")
        elif share_in.expires_in_hours:
            expires_at = datetime.now(timezone.utc) + timedelta(hours=share_in.expires_in_hours)

        token = generate_share_token(32)

        shared_link = SharedLink(
            file_id=share_in.file_id,
            folder_id=target_folder_id,
            created_by_user_id=owner_id,
            share_token=token,
            permission=share_in.permission,
            expires_at=expires_at,
            is_active=True,
            access_count=0,
        )
        db.add(shared_link)
        await db.commit()
        await db.refresh(shared_link)

        return ShareResponse(
            id=shared_link.id,
            share_token=shared_link.share_token,
            share_url=f"/api/v1/shares/public/{token}",
            file_id=shared_link.file_id,
            folder_id=shared_link.folder_id,
            item_name=item_name,
            permission=shared_link.permission,
            expires_at=shared_link.expires_at,
            is_active=shared_link.is_active,
            access_count=shared_link.access_count,
            created_at=shared_link.created_at,
        )

    @staticmethod
    async def list_shares(
        db: AsyncSession,
        owner_id: str,
        search: Optional[str] = None,
        item_type: Optional[str] = None,
        permission: Optional[str] = None,
        status: Optional[str] = None,
        sort_by: str = "created_at",
        order: str = "desc",
    ) -> List[ShareResponse]:
        query = select(SharedLink).where(SharedLink.created_by_user_id == owner_id)

        if item_type:
            it = item_type.lower().strip()
            if it == "file":
                query = query.where(SharedLink.file_id.is_not(None))
            elif it == "folder":
                query = query.where(SharedLink.file_id.is_(None))

        if permission:
            query = query.where(SharedLink.permission == permission.lower().strip())

        now = datetime.now(timezone.utc)
        if status:
            st = status.lower().strip()
            if st == "active":
                query = query.where(
                    SharedLink.is_active.is_(True),
                    (SharedLink.expires_at.is_(None)) | (SharedLink.expires_at > now),
                )
            elif st == "expired":
                query = query.where(
                    SharedLink.expires_at.is_not(None),
                    SharedLink.expires_at <= now,
                )
            elif st == "inactive":
                query = query.where(SharedLink.is_active.is_(False))

        sort_col = SharedLink.created_at
        if sort_by == "expires_at":
            sort_col = SharedLink.expires_at
        elif sort_by in ("access_count", "views"):
            sort_col = SharedLink.access_count

        if order and order.lower() == "asc":
            query = query.order_by(sort_col.asc())
        else:
            query = query.order_by(sort_col.desc())

        result = await db.execute(query)
        shares = list(result.scalars().all())

        responses: List[ShareResponse] = []
        for s in shares:
            name = "Item"
            if s.file:
                name = s.file.name
            elif s.folder:
                name = s.folder.name

            if search and search.strip():
                term = search.strip().lower()
                if term not in name.lower() and term not in s.share_token.lower():
                    continue

            responses.append(
                ShareResponse(
                    id=s.id,
                    share_token=s.share_token,
                    share_url=f"/api/v1/shares/public/{s.share_token}",
                    file_id=s.file_id,
                    folder_id=s.folder_id,
                    item_name=name,
                    permission=s.permission,
                    expires_at=s.expires_at,
                    is_active=s.is_active,
                    access_count=s.access_count,
                    created_at=s.created_at,
                )
            )

        if sort_by in ("name", "item_name"):
            reverse = (order.lower() == "desc") if order else False
            responses.sort(key=lambda r: r.item_name.lower(), reverse=reverse)

        return responses

    @staticmethod
    async def revoke_share(db: AsyncSession, share_id: str, owner_id: str) -> None:
        result = await db.execute(
            select(SharedLink).where(
                SharedLink.id == share_id,
                SharedLink.created_by_user_id == owner_id,
            )
        )
        share = result.scalar_one_or_none()
        if not share:
            raise NotFoundError("SharedLink", share_id)

        await db.delete(share)
        await db.commit()

    @staticmethod
    async def _is_folder_descendant_of(
        db: AsyncSession, folder_id: str, root_folder_id: str
    ) -> Tuple[bool, List[Dict[str, str]]]:
        """
        Check if folder_id is equal to or a descendant of root_folder_id.
        Returns (is_descendant, breadcrumbs_from_root_to_folder).
        """
        if folder_id == root_folder_id:
            root_f = await db.get(Folder, root_folder_id)
            if not root_f:
                return False, []
            return True, [{"id": root_f.id, "name": root_f.name}]

        chain = []
        curr_id: Optional[str] = folder_id
        visited = set()
        while curr_id:
            if curr_id in visited:
                break
            visited.add(curr_id)
            f = await db.get(Folder, curr_id)
            if not f or f.is_deleted:
                return False, []
            chain.append({"id": f.id, "name": f.name})
            if f.id == root_folder_id:
                chain.reverse()
                return True, chain
            curr_id = f.parent_id

        return False, []

    @staticmethod
    async def access_public_share(
        db: AsyncSession,
        share_token: str,
        storage: StorageBackend,
        subfolder_id: Optional[str] = None,
    ) -> PublicShareAccessResponse:
        result = await db.execute(
            select(SharedLink).where(SharedLink.share_token == share_token)
        )
        share = result.scalar_one_or_none()
        if not share or not share.is_active:
            raise NotFoundError("Shared link", share_token, message="Share link not found or inactive")

        if share.is_expired:
            raise PermissionDeniedError("This share link has expired")

        # Increment access count
        share.access_count += 1
        await db.commit()

        # Extract sharer details
        shared_by_name = None
        shared_by_email = None
        if share.created_by:
            shared_by_name = share.created_by.full_name or share.created_by.email
            shared_by_email = share.created_by.email

        if share.file:
            if share.file.is_deleted or (share.file.folder_id and await FolderService.is_folder_in_trash(db, share.file.folder_id)):
                raise NotFoundError("Shared link", share_token, message="Share link not found or inactive")

            file_obj = share.file
            blob = file_obj.blob
            download_url = None
            preview_url = None
            thumbnail_url = None
            if blob:
                if share.permission == "download":
                    download_url = await storage.generate_presigned_download_url(
                        key=blob.s3_key,
                        expires_in=3600,
                        filename=file_obj.name,
                        content_type=blob.content_type,
                    )
                preview_url = await storage.generate_presigned_download_url(
                    key=blob.s3_key,
                    expires_in=3600,
                    filename=None,
                    content_type=blob.content_type,
                )
            if file_obj.thumbnail_s3_key:
                thumbnail_url = await storage.generate_presigned_download_url(
                    key=file_obj.thumbnail_s3_key,
                    expires_in=3600,
                )

            return PublicShareAccessResponse(
                share_token=share_token,
                item_type="file",
                name=file_obj.name,
                permission=share.permission,
                shared_by_name=shared_by_name,
                shared_by_email=shared_by_email,
                file_size=file_obj.file_size,
                content_type=blob.content_type if blob else "application/octet-stream",
                download_url=download_url,
                preview_url=preview_url,
                thumbnail_url=thumbnail_url,
                expires_at=share.expires_at,
            )

        elif share.folder:
            if share.folder.is_deleted or await FolderService.is_folder_in_trash(db, share.folder.id):
                raise NotFoundError("Shared link", share_token, message="Share link not found or inactive")

            target_folder = share.folder
            breadcrumbs = [{"id": share.folder.id, "name": share.folder.name}]
            if subfolder_id and subfolder_id != share.folder.id:
                is_valid, b_crumbs = await ShareService._is_folder_descendant_of(
                    db, subfolder_id, share.folder.id
                )
                if is_valid:
                    sub_f = await db.get(Folder, subfolder_id)
                    if sub_f and not sub_f.is_deleted:
                        target_folder = sub_f
                        breadcrumbs = b_crumbs

            # List active files and subfolders in current folder
            f_res = await db.execute(
                select(File).where(File.folder_id == target_folder.id, File.is_deleted.is_(False)).order_by(File.name.asc())
            )
            files = list(f_res.scalars().all())

            sf_res = await db.execute(
                select(Folder).where(Folder.parent_id == target_folder.id, Folder.is_deleted.is_(False)).order_by(Folder.name.asc())
            )
            subfolders = list(sf_res.scalars().all())

            files_data = [
                {
                    "id": f.id,
                    "name": f.name,
                    "file_size": f.file_size,
                    "content_type": f.blob.content_type if f.blob else "application/octet-stream",
                    "created_at": f.created_at.isoformat() if f.created_at else None,
                }
                for f in files
            ]
            subfolders_data = [
                {"id": sf.id, "name": sf.name}
                for sf in subfolders
            ]

            return PublicShareAccessResponse(
                share_token=share_token,
                item_type="folder",
                name=target_folder.name,
                permission=share.permission,
                shared_by_name=shared_by_name,
                shared_by_email=shared_by_email,
                expires_at=share.expires_at,
                folder_id=target_folder.id,
                breadcrumbs=breadcrumbs,
                files=files_data,
                subfolders=subfolders_data,
            )

        raise NotFoundError("Shared item", share_token)

    @staticmethod
    async def access_public_shared_file(
        db: AsyncSession,
        share_token: str,
        file_id: str,
        storage: StorageBackend,
    ) -> PublicShareAccessResponse:
        """
        Publicly access a specific file located within a shared folder.
        Inherits the folder share's permission and expiration.
        """
        result = await db.execute(
            select(SharedLink).where(SharedLink.share_token == share_token)
        )
        share = result.scalar_one_or_none()
        if not share or not share.is_active:
            raise NotFoundError("Shared link", share_token, message="Share link not found or inactive")

        if share.is_expired:
            raise PermissionDeniedError("This share link has expired")

        if not share.folder:
            raise NotFoundError("Shared folder", share_token, message="Share link is not a folder")

        if share.folder.is_deleted or await FolderService.is_folder_in_trash(db, share.folder.id):
            raise NotFoundError("Shared folder", share_token, message="Shared folder is no longer active")

        file_obj = await db.get(File, file_id)
        if not file_obj or file_obj.is_deleted:
            raise NotFoundError("File", file_id)

        if not file_obj.folder_id:
            raise PermissionDeniedError("File is not part of this shared folder")

        is_descendant, _ = await ShareService._is_folder_descendant_of(
            db, file_obj.folder_id, share.folder.id
        )
        if not is_descendant:
            raise PermissionDeniedError("File is not part of this shared folder")

        shared_by_name = None
        shared_by_email = None
        if share.created_by:
            shared_by_name = share.created_by.full_name or share.created_by.email
            shared_by_email = share.created_by.email

        blob = file_obj.blob
        download_url = None
        preview_url = None
        thumbnail_url = None
        if blob:
            if share.permission == "download":
                download_url = await storage.generate_presigned_download_url(
                    key=blob.s3_key,
                    expires_in=3600,
                    filename=file_obj.name,
                    content_type=blob.content_type,
                )
            preview_url = await storage.generate_presigned_download_url(
                key=blob.s3_key,
                expires_in=3600,
                filename=None,
                content_type=blob.content_type,
            )
        if file_obj.thumbnail_s3_key:
            thumbnail_url = await storage.generate_presigned_download_url(
                key=file_obj.thumbnail_s3_key,
                expires_in=3600,
            )

        return PublicShareAccessResponse(
            share_token=share_token,
            item_type="file",
            name=file_obj.name,
            permission=share.permission,
            shared_by_name=shared_by_name,
            shared_by_email=shared_by_email,
            file_size=file_obj.file_size,
            content_type=blob.content_type if blob else "application/octet-stream",
            download_url=download_url,
            preview_url=preview_url,
            thumbnail_url=thumbnail_url,
            expires_at=share.expires_at,
        )

    @staticmethod
    async def download_public_shared_folder(
        db: AsyncSession,
        share_token: str,
        storage: StorageBackend,
    ) -> Dict[str, str]:
        """
        Bundle all contents of a shared folder into a ZIP file in storage and
        return a presigned download URL with the archive name.
        Returns {"download_url": presigned_url, "filename": archive_name}.
        """
        import io
        import time
        import zipfile

        result = await db.execute(
            select(SharedLink).where(SharedLink.share_token == share_token)
        )
        share = result.scalar_one_or_none()
        if not share or not share.is_active:
            raise NotFoundError("Shared link", share_token, message="Share link not found or inactive")

        if share.is_expired:
            raise PermissionDeniedError("This share link has expired")

        if share.permission != "download":
            raise PermissionDeniedError("This shared folder is view-only and cannot be downloaded")

        target_folder = share.folder
        if not target_folder:
            raise NotFoundError("Shared folder", share_token, message="Share link is not a folder")

        if target_folder.is_deleted or await FolderService.is_folder_in_trash(db, target_folder.id):
            raise NotFoundError("Shared folder", share_token, message="Shared folder is no longer active")

        # Save folder attributes BEFORE session commit to avoid expired relationship issues
        folder_id = target_folder.id
        folder_name = target_folder.name

        # Increment access count
        share.access_count += 1
        await db.commit()

        zip_buffer = io.BytesIO()
        has_entries = False
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            queue = [(folder_id, "")]
            while queue:
                curr_folder_id, curr_path = queue.pop(0)

                # Fetch all non-deleted files in this folder with explicit blob selectinload
                f_res = await db.execute(
                    select(File)
                    .options(selectinload(File.blob))
                    .where(File.folder_id == curr_folder_id, File.is_deleted.is_(False))
                )
                files = list(f_res.scalars().all())
                for f in files:
                    if f.blob and f.blob.s3_key:
                        try:
                            file_data = await storage.download_bytes(f.blob.s3_key)
                            entry_path = f"{curr_path}/{f.name}".lstrip("/")
                            zf.writestr(entry_path, file_data)
                            has_entries = True
                        except Exception as e:
                            logger.warning(f"Could not read blob for file {f.name} ({f.blob.s3_key}): {e}")

                # Fetch all non-deleted subfolders in this folder
                sf_res = await db.execute(
                    select(Folder).where(Folder.parent_id == curr_folder_id, Folder.is_deleted.is_(False))
                )
                subfolders = list(sf_res.scalars().all())
                for sf in subfolders:
                    sub_path = f"{curr_path}/{sf.name}".lstrip("/")
                    # Write directory entry to preserve empty subfolders
                    zf.writestr(f"{sub_path}/", b"")
                    has_entries = True
                    queue.append((sf.id, sub_path))

            if not has_entries:
                zf.writestr(".empty", b"")

        zip_bytes = zip_buffer.getvalue()
        archive_name = f"{folder_name}.zip"

        # Upload zip to storage with temporary key and generate a presigned download URL
        zip_key = f"temp_shares/{share_token}_{int(time.time())}.zip"
        await storage.upload_bytes(zip_key, zip_bytes, content_type="application/zip")

        download_url = await storage.generate_presigned_download_url(
            key=zip_key,
            expires_in=3600,
            filename=archive_name,
            content_type="application/zip",
        )

        return {"download_url": download_url, "filename": archive_name}

