from datetime import datetime
from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class ShareCreate(BaseModel):
    file_id: Optional[str] = Field(None, description="File ID to share")
    folder_id: Optional[str] = Field(None, description="Folder ID to share")
    permission: str = Field("download", description="'view' or 'download'")
    expires_in_hours: Optional[int] = Field(None, ge=1, description="Expiration time in hours (optional)")
    expires_at: Optional[datetime] = Field(None, description="Exact expiration datetime ISO 8601 (optional)")


class ShareResponse(BaseModel):
    id: str
    share_token: str
    share_url: str
    file_id: Optional[str] = None
    folder_id: Optional[str] = None
    item_name: str
    permission: str
    expires_at: Optional[datetime] = None
    is_active: bool
    access_count: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PublicShareAccessResponse(BaseModel):
    share_token: str
    item_type: str  # "file" or "folder"
    name: str
    permission: str
    shared_by_name: Optional[str] = None
    shared_by_email: Optional[str] = None
    file_size: Optional[int] = None
    content_type: Optional[str] = None
    download_url: Optional[str] = None
    preview_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    expires_at: Optional[datetime] = None
    folder_id: Optional[str] = None
    breadcrumbs: Optional[List[Any]] = None
    files: Optional[List[Any]] = None
    subfolders: Optional[List[Any]] = None

