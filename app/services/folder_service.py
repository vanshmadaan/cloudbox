from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError, QuotaExceededError, ValidationError
from app.core.logging import logger
from app.models.file import File
from app.models.folder import Folder
from app.models.user import User
from app.schemas.folder import FolderBreadcrumb, FolderCreate, FolderResponse, FolderTreeResponse, FolderUpdate, TrashFolderResponse
from app.storage.base import StorageBackend


class FolderService:
    """Business logic for hierarchical folder trees, breadcrumbs, soft-delete, and trash retention."""

    @staticmethod
    async def is_folder_in_trash(db: AsyncSession, folder_id: Optional[str]) -> bool:
        """Traverse up the folder hierarchy to check if this folder or any ancestor is deleted."""
        if not folder_id:
            return False
        curr_id: Optional[str] = folder_id
        visited = set()
        while curr_id:
            if curr_id in visited:
                break
            visited.add(curr_id)
            res = await db.execute(select(Folder.parent_id, Folder.is_deleted).where(Folder.id == curr_id))
            row = res.first()
            if not row:
                return True  # Parent folder missing
            parent_id, is_deleted = row
            if is_deleted:
                return True
            curr_id = parent_id
        return False

    @staticmethod
    async def create_folder(
        db: AsyncSession,
        owner_id: str,
        folder_in: FolderCreate,
    ) -> Folder:
        path = f"/{folder_in.name}"
        if folder_in.parent_id:
            parent_result = await db.execute(
                select(Folder).where(Folder.id == folder_in.parent_id)
            )
            parent = parent_result.scalar_one_or_none()
            if not parent or parent.is_deleted or await FolderService.is_folder_in_trash(db, folder_in.parent_id):
                raise NotFoundError("Parent folder", folder_in.parent_id)
            if parent.owner_id != owner_id:
                raise PermissionDeniedError("Cannot create subfolder in another user's folder")
            path = f"{parent.path.rstrip('/')}/{folder_in.name}"

        # Check for duplicate folder with the same name under the parent (among active folders)
        query = select(Folder).where(
            Folder.owner_id == owner_id,
            Folder.name == folder_in.name,
            Folder.is_deleted.is_(False),
        )
        if folder_in.parent_id:
            query = query.where(Folder.parent_id == folder_in.parent_id)
        else:
            query = query.where(Folder.parent_id.is_(None))

        existing = (await db.execute(query)).scalar_one_or_none()
        if existing:
            raise ConflictError(
                message=f"Folder with name '{folder_in.name}' already exists in this directory",
                code="FOLDER_ALREADY_EXISTS",
            )

        db_folder = Folder(
            name=folder_in.name,
            parent_id=folder_in.parent_id,
            owner_id=owner_id,
            path=path,
            is_deleted=False,
        )
        db.add(db_folder)
        await db.commit()
        await db.refresh(db_folder)
        return db_folder

    @staticmethod
    async def get_folder(db: AsyncSession, folder_id: str, owner_id: str) -> Folder:
        result = await db.execute(select(Folder).where(Folder.id == folder_id))
        folder = result.scalar_one_or_none()
        if not folder or folder.is_deleted:
            raise NotFoundError("Folder", folder_id)
        if folder.owner_id != owner_id:
            raise PermissionDeniedError("Access to this folder is denied")
        if await FolderService.is_folder_in_trash(db, folder.parent_id):
            raise NotFoundError("Folder", folder_id)
        return folder

    @staticmethod
    async def list_folders(
        db: AsyncSession,
        owner_id: str,
        parent_id: Optional[str] = None,
        search: Optional[str] = None,
        sort_by: str = "name",
        order: str = "asc",
    ) -> List[Folder]:
        if parent_id and await FolderService.is_folder_in_trash(db, parent_id):
            return []

        query = select(Folder).where(
            Folder.owner_id == owner_id,
            Folder.is_deleted.is_(False),
        )
        if parent_id:
            query = query.where(Folder.parent_id == parent_id)
        elif not search:
            query = query.where(Folder.parent_id.is_(None))

        if search and search.strip():
            query = query.where(Folder.name.ilike(f"%{search.strip()}%"))

        sort_col = Folder.name
        if sort_by == "created_at":
            sort_col = Folder.created_at
        elif sort_by == "updated_at":
            sort_col = Folder.updated_at

        if order and order.lower() == "desc":
            query = query.order_by(sort_col.desc())
        else:
            query = query.order_by(sort_col.asc())

        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_breadcrumbs(
        db: AsyncSession,
        folder_id: Optional[str],
        owner_id: str,
    ) -> List[FolderBreadcrumb]:
        breadcrumbs: List[FolderBreadcrumb] = [FolderBreadcrumb(id=None, name="Home")]
        if not folder_id:
            return breadcrumbs

        curr_id: Optional[str] = folder_id
        chain: List[FolderBreadcrumb] = []
        visited = set()

        while curr_id:
            if curr_id in visited:
                break
            visited.add(curr_id)
            res = await db.execute(
                select(Folder.id, Folder.name, Folder.parent_id, Folder.is_deleted, Folder.owner_id)
                .where(Folder.id == curr_id)
            )
            row = res.first()
            if not row:
                return [FolderBreadcrumb(id=None, name="Home")]
            f_id, f_name, f_parent_id, f_is_deleted, f_owner_id = row
            if f_is_deleted or f_owner_id != owner_id:
                return [FolderBreadcrumb(id=None, name="Home")]
            chain.append(FolderBreadcrumb(id=f_id, name=f_name))
            curr_id = f_parent_id

        chain.reverse()
        breadcrumbs.extend(chain)
        return breadcrumbs

    @staticmethod
    async def get_tree(db: AsyncSession, owner_id: str) -> List[FolderTreeResponse]:
        """Fetch active user folders and build a nested tree structure."""
        result = await db.execute(
            select(Folder).where(
                Folder.owner_id == owner_id,
                Folder.is_deleted.is_(False),
            )
        )
        all_folders = list(result.scalars().all())

        nodes: Dict[str, FolderTreeResponse] = {
            f.id: FolderTreeResponse(id=f.id, name=f.name, parent_id=f.parent_id, children=[])
            for f in all_folders
        }
        root_nodes: List[FolderTreeResponse] = []

        for f in all_folders:
            node = nodes[f.id]
            if f.parent_id and f.parent_id in nodes:
                nodes[f.parent_id].children.append(node)
            elif not f.parent_id:
                root_nodes.append(node)

        return root_nodes

    @staticmethod
    async def update_folder(
        db: AsyncSession,
        folder_id: str,
        owner_id: str,
        folder_in: FolderUpdate,
    ) -> Folder:
        folder = await FolderService.get_folder(db, folder_id, owner_id)
        old_path = folder.path

        new_name = folder_in.name if folder_in.name is not None else folder.name
        new_parent_id = folder.parent_id

        if "parent_id" in folder_in.model_fields_set:
            target_parent_id = None if folder_in.parent_id in (None, "", "root") else folder_in.parent_id
            if target_parent_id != folder.parent_id:
                if target_parent_id == folder_id:
                    raise ValidationError("A folder cannot be moved into itself")

                if target_parent_id is not None:
                    target_parent_res = await db.execute(
                        select(Folder).where(Folder.id == target_parent_id)
                    )
                    target_parent = target_parent_res.scalar_one_or_none()
                    if not target_parent or target_parent.is_deleted or await FolderService.is_folder_in_trash(db, target_parent_id) or target_parent.owner_id != owner_id:
                        raise NotFoundError("Target parent folder", target_parent_id)

                    # Circular dependency check
                    curr: Optional[Folder] = target_parent
                    while curr:
                        if curr.id == folder_id:
                            raise ValidationError("Cannot move a folder into one of its subfolders")
                        if not curr.parent_id:
                            break
                        curr_res = await db.execute(select(Folder).where(Folder.id == curr.parent_id))
                        curr = curr_res.scalar_one_or_none()

                new_parent_id = target_parent_id

        # Validate duplicate folder name in target parent
        if new_name != folder.name or new_parent_id != folder.parent_id:
            parent_filter = Folder.parent_id.is_(None) if new_parent_id is None else (Folder.parent_id == new_parent_id)
            dup_q = select(Folder).where(
                Folder.owner_id == owner_id,
                parent_filter,
                Folder.name == new_name,
                Folder.id != folder_id,
                Folder.is_deleted.is_(False),
            )
            if (await db.execute(dup_q)).scalar_one_or_none():
                loc_desc = "Home" if new_parent_id is None else "this folder"
                raise ValidationError(f"Folder with name '{new_name}' already exists in {loc_desc}")

        # Update path
        parent_path = "/"
        if new_parent_id:
            p_res = await db.execute(select(Folder).where(Folder.id == new_parent_id))
            p = p_res.scalar_one_or_none()
            if p:
                parent_path = p.path.rstrip("/") + "/"

        new_path = f"{parent_path.rstrip('/')}/{new_name}"

        folder.name = new_name
        folder.parent_id = new_parent_id
        folder.path = new_path
        folder.updated_at = datetime.now(timezone.utc)

        # Update paths of all descendant folders
        if old_path != new_path:
            desc_res = await db.execute(
                select(Folder).where(
                    Folder.owner_id == owner_id,
                    Folder.path.like(f"{old_path}/%"),
                )
            )
            for desc in desc_res.scalars().all():
                desc.path = new_path + desc.path[len(old_path):]

        await db.commit()
        await db.refresh(folder)
        return folder

    @staticmethod
    async def delete_folder(
        db: AsyncSession,
        folder_id: str,
        owner_id: str,
        storage: Optional[StorageBackend] = None,
    ) -> None:
        """
        Soft-delete a folder (move to trash):
        1. Marks ONLY this root folder as is_deleted = True, deleted_at = UTC NOW.
        2. Descendant folders and files are NOT marked deleted.
        3. Active descendant files have their quota refunded.
        4. Shared links for the folder and all descendant files are deactivated.
        """
        query = select(Folder).where(
            Folder.id == folder_id,
            Folder.owner_id == owner_id,
            Folder.is_deleted.is_(False),
        )
        result = await db.execute(query)
        folder = result.scalar_one_or_none()
        if not folder:
            raise NotFoundError("Folder", folder_id)

        # 1. Collect all descendant subfolder IDs recursively
        all_folder_ids = [folder_id]
        queue = [folder_id]
        while queue:
            current_pid = queue.pop(0)
            child_res = await db.execute(
                select(Folder.id).where(
                    Folder.parent_id == current_pid,
                    Folder.owner_id == owner_id,
                )
            )
            child_ids = list(child_res.scalars().all())
            all_folder_ids.extend(child_ids)
            queue.extend(child_ids)

        # 2. Find all files in the hierarchy
        files_res = await db.execute(
            select(File).where(
                File.folder_id.in_(all_folder_ids),
                File.owner_id == owner_id,
            )
        )
        files = list(files_res.scalars().all())

        # 3. Refund quota ONLY for active files (is_deleted == False)
        # Note: We do NOT mutate is_active on file share links; they remain unchanged in DB
        # but are logically inaccessible because their ancestor folder is in trash.
        user_res = await db.execute(select(User).where(User.id == owner_id))
        user = user_res.scalar_one()

        for file_obj in files:
            if not file_obj.is_deleted:
                user.storage_used_bytes = max(0, user.storage_used_bytes - file_obj.file_size)

        # 4. Deactivate direct share links for this folder (where file_id is None)
        for share in folder.shared_links:
            if share.file_id is None:
                share.is_active = False

        # 5. Mark only the root folder as deleted
        folder.is_deleted = True
        folder.deleted_at = datetime.now(timezone.utc)

        await db.commit()
        logger.info(f"Folder {folder_id} ('{folder.name}') soft-deleted to trash for user {owner_id}.")

    @staticmethod
    async def list_trash_folders(
        db: AsyncSession,
        owner_id: str,
        search: Optional[str] = None,
        sort_by: str = "deleted_at",
        order: str = "desc",
    ) -> List[TrashFolderResponse]:
        """List soft-deleted folders in trash belonging to the user."""
        query = (
            select(Folder)
            .where(
                Folder.owner_id == owner_id,
                Folder.is_deleted.is_(True),
            )
        )
        if search and search.strip():
            query = query.where(Folder.name.ilike(f"%{search.strip()}%"))

        sort_col = Folder.deleted_at
        if sort_by == "name":
            sort_col = Folder.name
        elif sort_by == "created_at":
            sort_col = Folder.created_at

        if order and order.lower() == "asc":
            query = query.order_by(sort_col.asc())
        else:
            query = query.order_by(sort_col.desc())

        result = await db.execute(query)
        folders = list(result.scalars().all())

        return [
            TrashFolderResponse(
                id=f.id,
                name=f.name,
                parent_id=f.parent_id,
                path=f.path,
                deleted_at=f.deleted_at or f.created_at,
                days_until_purge=f.days_until_purge(retention_days=14),
                created_at=f.created_at,
            )
            for f in folders
        ]

    @staticmethod
    async def restore_folder(
        db: AsyncSession,
        folder_id: str,
        owner_id: str,
    ) -> FolderResponse:
        """
        Restore a soft-deleted folder from trash back to active status:
        1. Checks quota availability for all active descendant files (is_deleted == False).
        2. If parent_id is missing or in trash, restores to root.
        3. Sets is_deleted = False, deleted_at = None.
        4. Re-adds quota for active descendant files.
        5. Reactivates unexpired shared links for the folder.
        6. Descendant files that were independently deleted remain in trash.
        """
        query = select(Folder).where(
            Folder.id == folder_id,
            Folder.owner_id == owner_id,
            Folder.is_deleted.is_(True),
        )
        result = await db.execute(query)
        folder = result.scalar_one_or_none()
        if not folder:
            raise NotFoundError("Deleted folder", folder_id)

        # 1. Collect all descendant subfolder IDs recursively
        all_folder_ids = [folder_id]
        queue = [folder_id]
        while queue:
            current_pid = queue.pop(0)
            child_res = await db.execute(
                select(Folder.id).where(
                    Folder.parent_id == current_pid,
                    Folder.owner_id == owner_id,
                )
            )
            child_ids = list(child_res.scalars().all())
            all_folder_ids.extend(child_ids)
            queue.extend(child_ids)

        # 2. Query all files in the hierarchy
        files_res = await db.execute(
            select(File).where(
                File.folder_id.in_(all_folder_ids),
                File.owner_id == owner_id,
            )
        )
        files = list(files_res.scalars().all())
        active_files = [f for f in files if not f.is_deleted]

        total_active_bytes = sum(f.file_size for f in active_files)

        # 3. Check quota
        user_res = await db.execute(select(User).where(User.id == owner_id))
        user = user_res.scalar_one()

        if user.storage_used_bytes + total_active_bytes > user.storage_quota_bytes:
            raise QuotaExceededError(
                used_bytes=user.storage_used_bytes,
                quota_bytes=user.storage_quota_bytes,
                requested_bytes=total_active_bytes,
            )

        # 4. Check parent folder availability
        if folder.parent_id:
            parent_res = await db.execute(
                select(Folder).where(
                    Folder.id == folder.parent_id,
                    Folder.owner_id == owner_id,
                )
            )
            parent = parent_res.scalar_one_or_none()
            if not parent or parent.is_deleted or await FolderService.is_folder_in_trash(db, folder.parent_id):
                folder.parent_id = None
                folder.path = f"/{folder.name}"
            else:
                folder.path = f"{parent.path.rstrip('/')}/{folder.name}"
        else:
            folder.path = f"/{folder.name}"

        # 5. Check for name conflict with active folder in destination
        parent_filter = Folder.parent_id.is_(None) if folder.parent_id is None else (Folder.parent_id == folder.parent_id)
        dup_q = select(Folder).where(
            Folder.owner_id == owner_id,
            parent_filter,
            Folder.name == folder.name,
            Folder.id != folder.id,
            Folder.is_deleted.is_(False),
        )
        if (await db.execute(dup_q)).scalar_one_or_none():
            loc_desc = "Home" if folder.parent_id is None else "the destination folder"
            raise ConflictError(
                message=f"A folder with name '{folder.name}' already exists in {loc_desc}. Please rename or delete the existing folder first.",
                code="FOLDER_ALREADY_EXISTS",
            )

        # 6. Restore folder state & quota
        folder.is_deleted = False
        folder.deleted_at = None
        user.storage_used_bytes += total_active_bytes

        # 6. Reactivate unexpired direct share links for this folder
        for share in folder.shared_links:
            if share.file_id is None and not share.is_expired:
                share.is_active = True

        await db.commit()
        await db.refresh(folder)
        logger.info(f"Folder {folder_id} ('{folder.name}') restored from trash for user {owner_id}.")
        return FolderResponse.model_validate(folder)

    @staticmethod
    async def permanent_delete_folder(
        db: AsyncSession,
        folder_id: str,
        owner_id: str,
        storage: StorageBackend,
    ) -> None:
        """
        Permanently delete a folder and EVERYTHING inside it:
        1. Collects all descendant subfolders and all contained files (including files already in trash).
        2. If folder was active, refunds quota for active files.
        3. Prunes unreferenced ContentBlobs (both in S3/storage and content_blobs table) and thumbnails.
        4. Removes all SharedLink records.
        5. Deletes all files and folder rows permanently from database.
        """
        query = select(Folder).where(
            Folder.id == folder_id,
            Folder.owner_id == owner_id,
        )
        result = await db.execute(query)
        folder = result.scalar_one_or_none()
        if not folder:
            raise NotFoundError("Folder", folder_id)

        # 1. Collect all descendant subfolder IDs recursively
        all_folder_ids = [folder_id]
        queue = [folder_id]
        while queue:
            current_pid = queue.pop(0)
            child_res = await db.execute(
                select(Folder.id).where(
                    Folder.parent_id == current_pid,
                    Folder.owner_id == owner_id,
                )
            )
            child_ids = list(child_res.scalars().all())
            all_folder_ids.extend(child_ids)
            queue.extend(child_ids)

        # 2. Query all files across this entire subtree (active and trashed)
        files_res = await db.execute(
            select(File).where(
                File.folder_id.in_(all_folder_ids),
                File.owner_id == owner_id,
            )
        )
        files = list(files_res.scalars().all())

        # 3. Quota refund if deleting an active folder directly
        user_res = await db.execute(select(User).where(User.id == owner_id))
        user = user_res.scalar_one()

        blobs_to_delete = []
        for file_obj in files:
            # If folder was active and file was active, refund quota
            if not folder.is_deleted and not file_obj.is_deleted:
                user.storage_used_bytes = max(0, user.storage_used_bytes - file_obj.file_size)

            # Decrement blob ref_counts
            blob = file_obj.blob
            if blob:
                blob.ref_count -= 1
                if blob.ref_count <= 0:
                    try:
                        await storage.delete_object(blob.s3_key)
                    except Exception as e:
                        logger.warning(f"Failed to delete blob {blob.s3_key}: {e}")
                    blobs_to_delete.append(blob)
            if file_obj.thumbnail_s3_key:
                try:
                    await storage.delete_object(file_obj.thumbnail_s3_key)
                except Exception as e:
                    logger.warning(f"Failed to delete thumbnail {file_obj.thumbnail_s3_key}: {e}")

        # Delete folder entity (cascades all subfolders, files, and shared links in the database)
        await db.delete(folder)
        await db.flush()

        # Delete unreferenced ContentBlobs from database table
        for blob in blobs_to_delete:
            await db.delete(blob)

        await db.commit()
        logger.info(f"Folder {folder_id} ('{folder.name}') and {len(files)} files permanently purged for user {owner_id}.")

    @staticmethod
    async def purge_expired_folders(
        db: AsyncSession,
        storage: StorageBackend,
        retention_days: int = 14,
    ) -> int:
        """
        Background maintenance job:
        Finds all folders soft-deleted >= retention_days ago and permanently deletes them and all contents.
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)
        query = select(Folder).where(
            Folder.is_deleted.is_(True),
            Folder.deleted_at <= cutoff_date,
        )
        result = await db.execute(query)
        expired_folders = list(result.scalars().all())

        purged_count = 0
        for folder in expired_folders:
            await FolderService.permanent_delete_folder(
                db=db,
                folder_id=folder.id,
                owner_id=folder.owner_id,
                storage=storage,
            )
            purged_count += 1

        return purged_count

    @staticmethod
    async def trash_folder_contents(
        db: AsyncSession,
        owner_id: str,
        folder_id: Optional[str] = None,
    ) -> Tuple[int, int]:
        """
        Move all direct child subfolders and files inside folder_id (or root) to trash.
        Returns (folders_trashed_count, files_trashed_count).
        """
        from app.services.file_service import FileService

        if folder_id:
            folder = await FolderService.get_folder(db, folder_id, owner_id)
            if folder.is_deleted or await FolderService.is_folder_in_trash(db, folder_id):
                raise NotFoundError("Folder", folder_id)

        # 1. Find direct child subfolders
        if folder_id:
            sf_query = select(Folder.id).where(
                Folder.parent_id == folder_id,
                Folder.owner_id == owner_id,
                Folder.is_deleted.is_(False),
            )
        else:
            sf_query = select(Folder.id).where(
                Folder.parent_id.is_(None),
                Folder.owner_id == owner_id,
                Folder.is_deleted.is_(False),
            )
        sf_res = await db.execute(sf_query)
        child_folder_ids = list(sf_res.scalars().all())

        # 2. Soft-delete each subfolder
        folders_trashed = 0
        for f_id in child_folder_ids:
            await FolderService.delete_folder(db, f_id, owner_id)
            folders_trashed += 1

        # 3. Find direct child files
        if folder_id:
            file_query = select(File.id).where(
                File.folder_id == folder_id,
                File.owner_id == owner_id,
                File.is_deleted.is_(False),
            )
        else:
            file_query = select(File.id).where(
                File.folder_id.is_(None),
                File.owner_id == owner_id,
                File.is_deleted.is_(False),
            )
        file_res = await db.execute(file_query)
        child_file_ids = list(file_res.scalars().all())

        # 4. Soft-delete each file
        files_trashed = 0
        for f_id in child_file_ids:
            await FileService.delete_file(db, f_id, owner_id)
            files_trashed += 1

        logger.info(
            f"Trashed contents of folder {folder_id or 'root'} for user {owner_id}: "
            f"{folders_trashed} folders and {files_trashed} files."
        )
        return folders_trashed, files_trashed

