from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class PresignedUploadRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="File name including extension")
    file_size: int = Field(..., gt=0, description="Size of file in bytes")
    folder_id: Optional[str] = Field(None, description="Destination folder ID, null for root")
    content_type: str = Field("application/octet-stream", description="MIME type of file")
    file_id: Optional[str] = Field(None, description="Existing file ID if overwriting an existing file")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("File name cannot be empty or whitespace only")
        return v

class PresignedUploadResponse(BaseModel):
    upload_url: str
    http_method: str
    headers: Dict[str, str]
    temp_s3_key: str
    file_id: Optional[str] = None
    expires_in: int


class CompleteUploadRequest(BaseModel):
    temp_s3_key: str = Field(..., description="The temporary S3 key where the client uploaded bytes")
    name: str = Field(..., min_length=1, max_length=255)
    file_size: int = Field(..., gt=0)
    checksum_sha256: str = Field(..., min_length=64, max_length=64, description="SHA-256 hex digest of file")
    folder_id: Optional[str] = None
    content_type: str = "application/octet-stream"
    file_id: Optional[str] = Field(None, description="Existing file ID if overwriting an existing file")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("File name cannot be empty or whitespace only")
        return v

class FileResponse(BaseModel):
    id: str
    name: str
    folder_id: Optional[str] = None
    owner_id: str
    file_size: int
    content_type: str
    status: str
    checksum_sha256: Optional[str] = None
    download_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    preview_url: Optional[str] = None
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FileDetailResponse(FileResponse):
    pass


class FileUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    folder_id: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("File name cannot be empty")
        return v


class FileDownloadResponse(BaseModel):
    download_url: str
    filename: str
    file_size: int
    content_type: str
    expires_in: int


class FilePreviewResponse(BaseModel):
    file_id: str
    filename: str
    file_size: int
    content_type: str
    preview_url: str
    download_url: str
    expires_in: int = 3600


class TrashFileResponse(BaseModel):
    id: str
    name: str
    folder_id: Optional[str] = None
    file_size: int
    content_type: str
    deleted_at: datetime
    days_until_purge: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

