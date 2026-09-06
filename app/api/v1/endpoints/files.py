from typing import List, Optional
from fastapi import APIRouter, File as FastAPIFile, Form, Header, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUserDep, QueueDep, SessionDep, StorageDep
from app.schemas.common import MessageResponse
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
from app.services.file_service import FileService

router = APIRouter()


@router.post(
    "/upload-url",
    response_model=PresignedUploadResponse,
    summary="Get Presigned S3 Upload URL",
)
async def get_presigned_upload_url(
    upload_req: PresignedUploadRequest,
    current_user: CurrentUserDep,
    db: SessionDep,
    storage: StorageDep,
) -> PresignedUploadResponse:
    """
    Generate a direct-to-S3 presigned upload URL.
    Enables clients to upload files of any size directly to S3, bypassing Lambda/API Gateway limits.
    """
    return await FileService.request_presigned_upload(
        db=db,
        user=current_user,
        upload_req=upload_req,
        storage=storage,
    )


@router.post(
    "/complete-upload",
    response_model=FileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Complete Direct S3 Upload",
)
async def complete_upload(
    complete_req: CompleteUploadRequest,
    current_user: CurrentUserDep,
    db: SessionDep,
    storage: StorageDep,
    queue: QueueDep,
) -> FileResponse:
    """
    Finalize upload after client uploads directly to S3.
    Performs SHA-256 deduplication, checks quota, and triggers async worker task.
    """
    return await FileService.complete_upload(
        db=db,
        user=current_user,
        complete_req=complete_req,
        storage=storage,
        queue_service=queue,
    )


@router.post(
    "/upload-direct",
    response_model=FileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Direct Multipart Upload",
)
async def upload_direct(
    current_user: CurrentUserDep,
    db: SessionDep,
    storage: StorageDep,
    queue: QueueDep,
    file: UploadFile = FastAPIFile(...),
    folder_id: Optional[str] = Form(None),
    file_id: Optional[str] = Form(None),
) -> FileResponse:
    """
    Multipart upload through API server (recommended for smaller files < 6MB or local testing).
    """
    content = await file.read()
    content_type = file.content_type or "application/octet-stream"
    filename = file.filename or "untitled_file"

    return await FileService.upload_direct(
        db=db,
        user=current_user,
        filename=filename,
        content=content,
        content_type=content_type,
        folder_id=folder_id,
        storage=storage,
        queue_service=queue,
        file_id=file_id,
    )


@router.get("/", response_model=List[FileResponse], summary="List Files")
async def list_files(
    current_user: CurrentUserDep,
    db: SessionDep,
    storage: StorageDep,
    folder_id: Optional[str] = Query(None, description="Filter files by folder ID (null for root)"),
    search: Optional[str] = Query(None, description="Filter files by name substring"),
    file_type: Optional[str] = Query(None, description="Filter files by type (image, video, audio, document, archive)"),
    sort_by: str = Query("created_at", description="Field to sort by (name, file_size, created_at, updated_at)"),
    order: str = Query("desc", description="Sort order (asc, desc)"),
) -> List[FileResponse]:
    """List active files with multi-criteria filtering and sorting."""
    return await FileService.list_files(
        db=db,
        owner_id=current_user.id,
        folder_id=folder_id,
        search=search,
        file_type=file_type,
        sort_by=sort_by,
        order=order,
        storage=storage,
    )


@router.get("/trash", response_model=List[TrashFileResponse], summary="List Files in Trash")
async def list_trash(
    current_user: CurrentUserDep,
    db: SessionDep,
    search: Optional[str] = Query(None, description="Filter trash files by name"),
    file_type: Optional[str] = Query(None, description="Filter trash files by type"),
    sort_by: str = Query("deleted_at", description="Field to sort by (name, file_size, deleted_at, created_at)"),
    order: str = Query("desc", description="Sort order (asc, desc)"),
) -> List[TrashFileResponse]:
    """List all soft-deleted files in trash with search, filtering, and sorting."""
    return await FileService.list_trash_files(
        db=db,
        owner_id=current_user.id,
        search=search,
        file_type=file_type,
        sort_by=sort_by,
        order=order,
    )


@router.delete("/trash/empty", response_model=MessageResponse, summary="Empty Trash Bin")
async def empty_trash(
    current_user: CurrentUserDep,
    db: SessionDep,
    storage: StorageDep,
) -> MessageResponse:
    """Permanently delete all folders and files in trash forever."""
    folders_count, files_count = await FileService.empty_trash(
        db=db,
        owner_id=current_user.id,
        storage=storage,
    )
    return MessageResponse(
        message=f"Empty trash completed: Permanently deleted {folders_count} folders and {files_count} files."
    )


@router.post("/trash/restore-all", response_model=MessageResponse, summary="Restore All from Trash")
async def restore_all_trash(
    current_user: CurrentUserDep,
    db: SessionDep,
    storage: StorageDep,
) -> MessageResponse:
    """Restore all folders and files currently in trash back to active directory."""
    folders_count, files_count = await FileService.restore_all_trash(
        db=db,
        owner_id=current_user.id,
        storage=storage,
    )
    return MessageResponse(
        message=f"Restored {folders_count} folders and {files_count} files from trash."
    )


@router.post("/purge-expired", response_model=MessageResponse, summary="Purge Expired Files")
async def purge_expired(
    current_user: CurrentUserDep,
    db: SessionDep,
    storage: StorageDep,
    retention_days: int = Query(14, ge=1, description="Retention window in days (default: 14)"),
) -> MessageResponse:
    """Trigger cleanup of files that have been in trash longer than retention days."""
    count = await FileService.purge_expired_files(
        db=db,
        storage=storage,
        retention_days=retention_days,
    )
    return MessageResponse(message=f"Purged {count} expired files successfully.")


# --- Local Storage Fallback Endpoints (For offline/testing without AWS S3) ---

@router.put("/local-storage-direct-upload", include_in_schema=False)
async def local_storage_put_handler(
    request: Request,
    key: str = Query(...),
    storage: StorageDep = None,
):
    """Local storage simulated PUT handler for local development presigned URLs."""
    body = await request.body()
    content_type = request.headers.get("content-type", "application/octet-stream")
    await storage.upload_bytes(key, body, content_type)
    return Response(status_code=200)


@router.get("/local-storage-stream", include_in_schema=False)
async def local_storage_stream_handler(
    key: str = Query(...),
    filename: Optional[str] = Query(None),
    storage: StorageDep = None,
):
    """Local storage simulated stream handler for local development downloads."""
    data = await storage.download_bytes(key)
    headers = {}
    if filename:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return Response(content=data, media_type="application/octet-stream", headers=headers)


@router.get("/{file_id}", response_model=FileDetailResponse, summary="Get File Details")
async def get_file(
    file_id: str,
    current_user: CurrentUserDep,
    db: SessionDep,
    storage: StorageDep,
) -> FileDetailResponse:
    """Retrieve file metadata and details."""
    return await FileService.get_file(
        db=db,
        file_id=file_id,
        owner_id=current_user.id,
        storage=storage,
    )


@router.get("/{file_id}/download", response_model=FileDownloadResponse, summary="Get Download Presigned URL")
async def get_download_url(
    file_id: str,
    current_user: CurrentUserDep,
    db: SessionDep,
    storage: StorageDep,
) -> FileDownloadResponse:
    """Generate a presigned S3 download URL for the file."""
    return await FileService.get_download_url(
        db=db,
        file_id=file_id,
        owner_id=current_user.id,
        storage=storage,
    )


@router.get("/{file_id}/preview", response_model=FilePreviewResponse, summary="Get Preview Presigned URL")
async def get_preview_url(
    file_id: str,
    current_user: CurrentUserDep,
    db: SessionDep,
    storage: StorageDep,
) -> FilePreviewResponse:
    """Generate a presigned inline preview URL for the file."""
    return await FileService.get_preview_url(
        db=db,
        file_id=file_id,
        owner_id=current_user.id,
        storage=storage,
    )


@router.patch("/{file_id}", response_model=FileResponse, summary="Update File")
async def update_file(
    file_id: str,
    file_in: FileUpdate,
    current_user: CurrentUserDep,
    db: SessionDep,
    storage: StorageDep,
) -> FileResponse:
    """Rename a file or move it to a different folder."""
    return await FileService.update_file(
        db=db,
        file_id=file_id,
        owner_id=current_user.id,
        file_in=file_in,
        storage=storage,
    )


@router.post("/{file_id}/restore", response_model=FileResponse, summary="Restore File from Trash")
async def restore_file(
    file_id: str,
    current_user: CurrentUserDep,
    db: SessionDep,
    storage: StorageDep,
) -> FileResponse:
    """Restore a soft-deleted file from trash back into active directory."""
    return await FileService.restore_file(
        db=db,
        file_id=file_id,
        owner_id=current_user.id,
        storage=storage,
    )


@router.delete("/{file_id}", response_model=MessageResponse, summary="Delete File (Move to Trash)")
async def delete_file(
    file_id: str,
    current_user: CurrentUserDep,
    db: SessionDep,
    storage: StorageDep,
) -> MessageResponse:
    """Soft-delete a file. It is retained in Trash for 14 days before permanent deletion."""
    await FileService.delete_file(
        db=db,
        file_id=file_id,
        owner_id=current_user.id,
        storage=storage,
    )
    return MessageResponse(
        message=f"File '{file_id}' moved to trash. It will be retained for 14 days before being deleted forever."
    )


@router.delete("/{file_id}/permanent", response_model=MessageResponse, summary="Permanently Delete File")
async def permanent_delete_file(
    file_id: str,
    current_user: CurrentUserDep,
    db: SessionDep,
    storage: StorageDep,
) -> MessageResponse:
    """Permanently delete a file immediately, removing metadata and storage bytes."""
    await FileService.permanent_delete_file(
        db=db,
        file_id=file_id,
        owner_id=current_user.id,
        storage=storage,
    )
    return MessageResponse(message=f"File '{file_id}' permanently deleted from storage.")

