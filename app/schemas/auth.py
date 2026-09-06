from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128, description="User password")
    full_name: str = Field(..., min_length=1, max_length=255, description="User full name")

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Full name is required and cannot be empty")
        return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenPayload(BaseModel):
    sub: Optional[str] = None
    exp: Optional[int] = None


class UserResponse(BaseModel):
    id: str
    email: EmailStr
    full_name: Optional[str] = None
    storage_quota_bytes: int
    storage_used_bytes: int
    storage_used_percentage: float
    is_active: bool
    is_superuser: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserQuotaResponse(BaseModel):
    storage_quota_bytes: int
    storage_used_bytes: int
    storage_available_bytes: int
    storage_used_percentage: float


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    message: str
    expires_in_seconds: int = 300
    debug_otp: Optional[str] = None
    delivered: bool = True
    delivery_warning: Optional[str] = None


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    new_password: str = Field(..., min_length=6, max_length=128, description="New password")
    confirm_password: str = Field(..., min_length=6, max_length=128, description="Confirm new password")
    otp: str = Field(..., min_length=6, max_length=6, pattern=r"^[0-9]{6}$", description="6-digit OTP code")


class ResetPasswordResponse(BaseModel):
    message: str

