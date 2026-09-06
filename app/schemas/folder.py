from datetime import datetime
from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class FolderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Folder name")
    parent_id: Optional[str] = Field(None, description="Parent folder ID, null for root")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Folder name cannot be empty or whitespace only")
        return v


class FolderUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    parent_id: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Folder name cannot be empty")
        return v


class FolderBreadcrumb(BaseModel):
    id: Optional[str]
    name: str


class FolderResponse(BaseModel):
    id: str
    name: str
    parent_id: Optional[str] = None
    owner_id: str
    path: str
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FolderTreeResponse(BaseModel):
    id: str
    name: str
    parent_id: Optional[str] = None
    children: List["FolderTreeResponse"] = []

    model_config = ConfigDict(from_attributes=True)


class TrashFolderResponse(BaseModel):
    id: str
    name: str
    parent_id: Optional[str] = None
    path: str
    deleted_at: datetime
    days_until_purge: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

