from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class AdminUserResponse(BaseModel):
    id: str
    email: EmailStr
    full_name: Optional[str] = None
    storage_quota_bytes: int
    storage_used_bytes: int
    storage_used_percentage: float
    is_active: bool
    is_superuser: bool
    file_count: int = 0
    folder_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminUserUpdate(BaseModel):
    storage_quota_bytes: Optional[int] = Field(None, ge=1048576, description="Quota in bytes (min 1MB)")
    is_active: Optional[bool] = None
    is_superuser: Optional[bool] = None


class AdminStatsResponse(BaseModel):
    total_users: int
    active_users: int
    total_files: int
    total_folders: int
    total_storage_used_bytes: int
    total_storage_quota_bytes: int
    total_blobs: int
    total_shares: int
