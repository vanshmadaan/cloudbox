from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import CurrentSuperuserDep, SessionDep, StorageDep
from app.core.exceptions import NotFoundError
from app.models.blob import ContentBlob
from app.models.file import File
from app.models.folder import Folder
from app.models.share import SharedLink
from app.models.user import User
from app.schemas.admin import (
    AdminStatsResponse,
    AdminUserResponse,
    AdminUserUpdate,
    AdminWipeStorageResponse,
)
from app.schemas.common import MessageResponse
from app.services.file_service import FileService

router = APIRouter()


@router.get("/stats", response_model=AdminStatsResponse, summary="Get System-Wide Storage & User Statistics")
async def get_admin_stats(
    db: SessionDep,
    _admin: CurrentSuperuserDep,
) -> AdminStatsResponse:
    """Retrieve aggregate statistics across all users, files, blobs, and shares."""
    total_users_res = await db.execute(select(func.count(User.id)))
    total_users = total_users_res.scalar() or 0

    active_users_res = await db.execute(select(func.count(User.id)).where(User.is_active.is_(True)))
    active_users = active_users_res.scalar() or 0

    total_files_res = await db.execute(select(func.count(File.id)).where(File.is_deleted.is_(False)))
    total_files = total_files_res.scalar() or 0

    total_folders_res = await db.execute(select(func.count(Folder.id)).where(Folder.is_deleted.is_(False)))
    total_folders = total_folders_res.scalar() or 0

    storage_used_res = await db.execute(select(func.coalesce(func.sum(User.storage_used_bytes), 0)))
    total_storage_used = storage_used_res.scalar() or 0

    storage_quota_res = await db.execute(select(func.coalesce(func.sum(User.storage_quota_bytes), 0)))
    total_storage_quota = storage_quota_res.scalar() or 0

    total_blobs_res = await db.execute(select(func.count(ContentBlob.id)))
    total_blobs = total_blobs_res.scalar() or 0

    total_shares_res = await db.execute(select(func.count(SharedLink.id)).where(SharedLink.is_active.is_(True)))
    total_shares = total_shares_res.scalar() or 0

    return AdminStatsResponse(
        total_users=total_users,
        active_users=active_users,
        total_files=total_files,
        total_folders=total_folders,
        total_storage_used_bytes=total_storage_used,
        total_storage_quota_bytes=total_storage_quota,
        total_blobs=total_blobs,
        total_shares=total_shares,
    )


@router.get("/users", response_model=List[AdminUserResponse], summary="List All Registered Users")
async def list_admin_users(
    db: SessionDep,
    _admin: CurrentSuperuserDep,
    search: Optional[str] = Query(None, description="Search by email or full name"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status ('active', 'disabled')"),
    role: Optional[str] = Query(None, description="Filter by role ('admin', 'user')"),
    sort_by: str = Query("created_at", description="Sort by 'created_at', 'email', 'storage_used_bytes', 'storage_quota_bytes'"),
    order: str = Query("desc", description="Sort order ('asc' or 'desc')"),
) -> List[AdminUserResponse]:
    """Retrieve all users with file and folder counts and storage metrics."""
    file_count_subq = (
        select(func.count(File.id))
        .where(File.owner_id == User.id, File.is_deleted.is_(False))
        .scalar_subquery()
    )
    folder_count_subq = (
        select(func.count(Folder.id))
        .where(Folder.owner_id == User.id, Folder.is_deleted.is_(False))
        .scalar_subquery()
    )

    query = select(
        User,
        file_count_subq.label("file_count"),
        folder_count_subq.label("folder_count"),
    )

    if search:
        s = f"%{search.strip()}%"
        query = query.where((User.email.ilike(s)) | (User.full_name.ilike(s)))

    if status_filter:
        sf = status_filter.lower().strip()
        if sf == "active":
            query = query.where(User.is_active.is_(True))
        elif sf in ("disabled", "inactive"):
            query = query.where(User.is_active.is_(False))

    if role:
        r = role.lower().strip()
        if r == "admin":
            query = query.where(User.is_superuser.is_(True))
        elif r == "user":
            query = query.where(User.is_superuser.is_(False))

    sort_mapping = {
        "email": User.email,
        "storage_used_bytes": User.storage_used_bytes,
        "storage_quota_bytes": User.storage_quota_bytes,
        "created_at": User.created_at,
    }
    sort_column = sort_mapping.get(sort_by, User.created_at)

    if order.lower() == "asc":
        query = query.order_by(sort_column.asc())
    else:
        query = query.order_by(sort_column.desc())

    result = await db.execute(query)
    rows = result.all()

    response = []
    for user, file_count, folder_count in rows:
        response.append(
            AdminUserResponse(
                id=user.id,
                email=user.email,
                full_name=user.full_name,
                storage_quota_bytes=user.storage_quota_bytes,
                storage_used_bytes=user.storage_used_bytes,
                storage_used_percentage=user.storage_used_percentage,
                is_active=user.is_active,
                is_superuser=user.is_superuser,
                file_count=file_count or 0,
                folder_count=folder_count or 0,
                created_at=user.created_at,
                updated_at=user.updated_at,
            )
        )
    return response


@router.patch("/users/{user_id}", response_model=AdminUserResponse, summary="Update User Quota & Permissions")
async def update_admin_user(
    user_id: str,
    payload: AdminUserUpdate,
    db: SessionDep,
    _admin: CurrentSuperuserDep,
) -> AdminUserResponse:
    """Modify user storage quota, active state, or superuser permissions."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("User", user_id)

    if payload.storage_quota_bytes is not None:
        user.storage_quota_bytes = payload.storage_quota_bytes

    if payload.is_active is not None:
        # Prevent admin from deactivating themselves
        if user.id == _admin.id and not payload.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Administrators cannot deactivate their own account",
            )
        user.is_active = payload.is_active

    if payload.is_superuser is not None:
        # Prevent admin from demoting themselves
        if user.id == _admin.id and not payload.is_superuser:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Administrators cannot revoke their own superuser status",
            )
        user.is_superuser = payload.is_superuser

    await db.commit()
    await db.refresh(user)

    file_count_res = await db.execute(
        select(func.count(File.id)).where(File.owner_id == user.id, File.is_deleted.is_(False))
    )
    folder_count_res = await db.execute(
        select(func.count(Folder.id)).where(Folder.owner_id == user.id, Folder.is_deleted.is_(False))
    )

    return AdminUserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        storage_quota_bytes=user.storage_quota_bytes,
        storage_used_bytes=user.storage_used_bytes,
        storage_used_percentage=user.storage_used_percentage,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        file_count=file_count_res.scalar() or 0,
        folder_count=folder_count_res.scalar() or 0,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


@router.post(
    "/users/{user_id}/wipe-storage",
    response_model=AdminWipeStorageResponse,
    summary="Wipe All Files & Folders for a Specific User (Free S3 Space)",
)
async def wipe_user_storage_endpoint(
    user_id: str,
    db: SessionDep,
    storage: StorageDep,
    _admin: CurrentSuperuserDep,
) -> AdminWipeStorageResponse:
    """
    Emergency space reclaim for a specific user:
    Permanently deletes all active and trashed files, folders, and thumbnails for this user,
    physically removing unreferenced blobs from Amazon S3 and resetting storage_used_bytes to 0.
    """
    user_res = await db.execute(select(User).where(User.id == user_id))
    user = user_res.scalar_one_or_none()
    if not user:
        raise NotFoundError("User", user_id)

    files_wiped, folders_wiped, bytes_freed = await FileService.wipe_user_storage(
        db=db,
        user_id=user_id,
        storage=storage,
    )

    return AdminWipeStorageResponse(
        user_id=user_id,
        users_affected=1,
        files_wiped=files_wiped,
        folders_wiped=folders_wiped,
        bytes_freed=bytes_freed,
        message=f"Successfully wiped storage for '{user.email}': {files_wiped} files and {folders_wiped} folders purged, freeing {bytes_freed} bytes from S3.",
    )


@router.post(
    "/wipe-all-storage",
    response_model=AdminWipeStorageResponse,
    summary="Emergency AWS Free Tier Reclaim: Wipe All Non-Admin Files",
)
async def wipe_all_non_admin_storage_endpoint(
    db: SessionDep,
    storage: StorageDep,
    admin: CurrentSuperuserDep,
) -> AdminWipeStorageResponse:
    """
    Emergency AWS Free Tier Protection:
    Permanently deletes all files and folders uploaded by all non-admin users from Amazon S3 and PostgreSQL.
    User accounts remain intact, but all their stored data is wiped and their quota usage is reset to 0 bytes.
    """
    users_affected, files_wiped, folders_wiped, bytes_freed = await FileService.wipe_all_non_admin_storage(
        db=db,
        storage=storage,
        exclude_user_id=admin.id,
    )

    return AdminWipeStorageResponse(
        user_id=None,
        users_affected=users_affected,
        files_wiped=files_wiped,
        folders_wiped=folders_wiped,
        bytes_freed=bytes_freed,
        message=f"Emergency reclaim complete across {users_affected} users: {files_wiped} files and {folders_wiped} folders purged, freeing {bytes_freed} bytes from S3.",
    )


@router.delete(
    "/users/{user_id}",
    response_model=MessageResponse,
    summary="Permanently Delete User Account and S3 Files",
)
async def delete_admin_user_endpoint(
    user_id: str,
    db: SessionDep,
    storage: StorageDep,
    admin: CurrentSuperuserDep,
) -> MessageResponse:
    """
    Permanently deletes a user account, all their files from Amazon S3, and all associated database records.
    Admins cannot delete their own account.
    """
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Administrators cannot delete their own account",
        )

    user_res = await db.execute(select(User).where(User.id == user_id))
    user = user_res.scalar_one_or_none()
    if not user:
        raise NotFoundError("User", user_id)

    email = user.email
    # First wipe all files and S3 storage objects
    await FileService.wipe_user_storage(db=db, user_id=user_id, storage=storage)

    # Then delete the user record
    await db.delete(user)
    await db.commit()

    return MessageResponse(
        message=f"User account '{email}' and all associated files were permanently deleted."
    )

