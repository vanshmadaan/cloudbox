from typing import List, Optional
from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUserDep, SessionDep, StorageDep
from app.schemas.common import MessageResponse
from app.schemas.folder import (
    FolderBreadcrumb,
    FolderCreate,
    FolderResponse,
    FolderTreeResponse,
    FolderUpdate,
    TrashFolderResponse,
)
from app.services.folder_service import FolderService

router = APIRouter()


@router.post("/", response_model=FolderResponse, status_code=status.HTTP_201_CREATED, summary="Create Folder")
async def create_folder(
    folder_in: FolderCreate,
    current_user: CurrentUserDep,
    db: SessionDep,
) -> FolderResponse:
    """Create a new folder or nested subfolder in the user's directory tree."""
    folder = await FolderService.create_folder(db, current_user.id, folder_in)
    return FolderResponse.model_validate(folder)


@router.get("/trash", response_model=List[TrashFolderResponse], summary="List Trash Folders")
async def list_trash_folders(
    current_user: CurrentUserDep,
    db: SessionDep,
    search: Optional[str] = Query(None, description="Search trash folder name"),
    sort_by: str = Query("deleted_at", description="Field to sort by (name, deleted_at, created_at)"),
    order: str = Query("desc", description="Sort order (asc, desc)"),
) -> List[TrashFolderResponse]:
    """Retrieve soft-deleted folders in trash with search and sorting."""
    return await FolderService.list_trash_folders(
        db=db,
        owner_id=current_user.id,
        search=search,
        sort_by=sort_by,
        order=order,
    )


@router.get("/", response_model=List[FolderResponse], summary="List Folders")
async def list_folders(
    current_user: CurrentUserDep,
    db: SessionDep,
    parent_id: Optional[str] = Query(None, description="Parent folder ID. Omit or null for root."),
    search: Optional[str] = Query(None, description="Search folder name substring"),
    sort_by: str = Query("name", description="Field to sort by (name, created_at, updated_at)"),
    order: str = Query("asc", description="Sort order (asc, desc)"),
) -> List[FolderResponse]:
    """List subfolders belonging to the authenticated user with search and sorting."""
    folders = await FolderService.list_folders(
        db=db,
        owner_id=current_user.id,
        parent_id=parent_id,
        search=search,
        sort_by=sort_by,
        order=order,
    )
    return [FolderResponse.model_validate(f) for f in folders]


@router.get("/tree", response_model=List[FolderTreeResponse], summary="Get Folder Tree")
async def get_folder_tree(
    current_user: CurrentUserDep,
    db: SessionDep,
) -> List[FolderTreeResponse]:
    """Retrieve full nested folder hierarchy for the current user."""
    return await FolderService.get_tree(db, current_user.id)


@router.get("/breadcrumbs", response_model=List[FolderBreadcrumb], summary="Get Breadcrumbs")
async def get_breadcrumbs(
    current_user: CurrentUserDep,
    db: SessionDep,
    folder_id: Optional[str] = Query(None, description="Folder ID to compute breadcrumbs for."),
) -> List[FolderBreadcrumb]:
    """Generate navigation breadcrumbs from root to specified folder."""
    return await FolderService.get_breadcrumbs(db, folder_id, current_user.id)


@router.get("/{folder_id}", response_model=FolderResponse, summary="Get Folder By ID")
async def get_folder(
    folder_id: str,
    current_user: CurrentUserDep,
    db: SessionDep,
) -> FolderResponse:
    """Get metadata for a single folder."""
    folder = await FolderService.get_folder(db, folder_id, current_user.id)
    return FolderResponse.model_validate(folder)


@router.patch("/{folder_id}", response_model=FolderResponse, summary="Update Folder")
async def update_folder(
    folder_id: str,
    folder_in: FolderUpdate,
    current_user: CurrentUserDep,
    db: SessionDep,
) -> FolderResponse:
    """Rename a folder or move it to a different parent."""
    folder = await FolderService.update_folder(db, folder_id, current_user.id, folder_in)
    return FolderResponse.model_validate(folder)


@router.delete("/{folder_id}", response_model=MessageResponse, summary="Soft Delete Folder")
async def delete_folder(
    folder_id: str,
    current_user: CurrentUserDep,
    db: SessionDep,
) -> MessageResponse:
    """Soft-delete a folder and move it to trash with 14-day retention."""
    await FolderService.delete_folder(
        db=db,
        folder_id=folder_id,
        owner_id=current_user.id,
    )
    return MessageResponse(message=f"Folder '{folder_id}' moved to trash (14-day retention)")


@router.post("/{folder_id}/restore", response_model=FolderResponse, summary="Restore Folder")
async def restore_folder(
    folder_id: str,
    current_user: CurrentUserDep,
    db: SessionDep,
) -> FolderResponse:
    """Restore a soft-deleted folder and its active contents from trash."""
    return await FolderService.restore_folder(db, folder_id, current_user.id)


@router.delete("/{folder_id}/permanent", response_model=MessageResponse, summary="Permanent Delete Folder")
async def permanent_delete_folder(
    folder_id: str,
    current_user: CurrentUserDep,
    db: SessionDep,
    storage: StorageDep,
) -> MessageResponse:
    """Permanently delete a folder and all its contents immediately."""
    await FolderService.permanent_delete_folder(
        db=db,
        folder_id=folder_id,
        owner_id=current_user.id,
        storage=storage,
    )
    return MessageResponse(message=f"Folder '{folder_id}' and all contents permanently deleted")


@router.post("/purge-expired", response_model=MessageResponse, summary="Purge Expired Folders")
async def purge_expired_folders(
    current_user: CurrentUserDep,
    db: SessionDep,
    storage: StorageDep,
    retention_days: int = Query(14, ge=1, description="Retention window in days"),
) -> MessageResponse:
    """Trigger cleanup of folders soft-deleted beyond retention window."""
    count = await FolderService.purge_expired_folders(db, storage, retention_days=retention_days)
    return MessageResponse(message=f"Purged {count} expired folders past {retention_days}-day retention window.")


@router.post("/trash-contents", response_model=MessageResponse, summary="Move Folder Contents to Trash")
async def trash_folder_contents(
    current_user: CurrentUserDep,
    db: SessionDep,
    folder_id: Optional[str] = Query(None, description="Folder ID whose contents to move to trash. Omit/null for root."),
) -> MessageResponse:
    """Move all direct child subfolders and files inside the specified folder (or root) to trash."""
    folders_count, files_count = await FolderService.trash_folder_contents(
        db=db,
        owner_id=current_user.id,
        folder_id=folder_id,
    )
    return MessageResponse(
        message=f"Moved {folders_count} folders and {files_count} files to trash."
    )

