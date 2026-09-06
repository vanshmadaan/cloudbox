from typing import List, Optional
from fastapi import APIRouter, Query, status
from fastapi.responses import Response

from app.api.deps import CurrentUserDep, SessionDep, StorageDep
from app.schemas.common import MessageResponse
from app.schemas.share import PublicShareAccessResponse, ShareCreate, ShareResponse
from app.services.share_service import ShareService

router = APIRouter()


@router.post("/", response_model=ShareResponse, status_code=status.HTTP_201_CREATED, summary="Create Share Link")
async def create_share_link(
    share_in: ShareCreate,
    current_user: CurrentUserDep,
    db: SessionDep,
) -> ShareResponse:
    """Generate a shareable token link for a file or folder with optional expiration."""
    return await ShareService.create_share_link(db, current_user.id, share_in)


@router.get("/", response_model=List[ShareResponse], summary="List User Share Links")
async def list_shares(
    current_user: CurrentUserDep,
    db: SessionDep,
    search: Optional[str] = Query(None, description="Search share item name or token"),
    item_type: Optional[str] = Query(None, description="Filter by item type (file, folder)"),
    permission: Optional[str] = Query(None, description="Filter by permission (view, download)"),
    status: Optional[str] = Query(None, description="Filter by status (active, expired, inactive)"),
    sort_by: str = Query("created_at", description="Field to sort by (created_at, expires_at, access_count, name)"),
    order: str = Query("desc", description="Sort order (asc, desc)"),
) -> List[ShareResponse]:
    """List all share links created by the current user with filtering and sorting."""
    return await ShareService.list_shares(
        db=db,
        owner_id=current_user.id,
        search=search,
        item_type=item_type,
        permission=permission,
        status=status,
        sort_by=sort_by,
        order=order,
    )


@router.delete("/{share_id}", response_model=MessageResponse, summary="Revoke Share Link")
async def revoke_share(
    share_id: str,
    current_user: CurrentUserDep,
    db: SessionDep,
) -> MessageResponse:
    """Revoke and deactivate a share link."""
    await ShareService.revoke_share(db, share_id, current_user.id)
    return MessageResponse(message="Share link revoked successfully")


@router.get("/public/{share_token}", response_model=PublicShareAccessResponse, summary="Access Shared Item (Public)")
async def access_public_share(
    share_token: str,
    db: SessionDep,
    storage: StorageDep,
    subfolder_id: Optional[str] = Query(None, description="Optional subfolder ID to explore inside a shared folder"),
) -> PublicShareAccessResponse:
    """
    Publicly access a shared file or folder via its unique share token without authentication.
    Supports exploring nested subfolders inside a shared folder root.
    """
    return await ShareService.access_public_share(db, share_token, storage, subfolder_id=subfolder_id)


@router.get("/public/{share_token}/file/{file_id}", response_model=PublicShareAccessResponse, summary="Access File in Shared Folder")
async def access_public_shared_file(
    share_token: str,
    file_id: str,
    db: SessionDep,
    storage: StorageDep,
) -> PublicShareAccessResponse:
    """
    Publicly access, preview, or download a specific file located within a shared folder hierarchy.
    Inherits the parent shared link's permissions.
    """
    return await ShareService.access_public_shared_file(db, share_token, file_id, storage)


@router.get("/public/{share_token}/download-folder", summary="Download Entire Shared Folder as ZIP")
async def download_public_shared_folder(
    share_token: str,
    db: SessionDep,
    storage: StorageDep,
):
    """
    Publicly download an entire shared folder as a ZIP file.
    Requires 'download' permission on the share link.
    Returns presigned download URL for direct, fast, resumable streaming.
    """
    return await ShareService.download_public_shared_folder(db, share_token, storage)

