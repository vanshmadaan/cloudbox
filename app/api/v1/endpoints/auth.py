from typing import Annotated
from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import CurrentUserDep, SessionDep, StorageDep
from app.core.config import settings
from app.core.rate_limit import auth_rate_limiter, otp_rate_limiter
from app.core.security import create_access_token
from app.schemas.common import MessageResponse
from app.schemas.auth import (
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
    Token,
    UserCreate,
    UserLogin,
    UserQuotaResponse,
    UserResponse,
)
from app.services.auth_service import AuthService

router = APIRouter()


@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED, summary="User Signup")
async def signup(
    user_in: UserCreate,
    db: SessionDep,
) -> UserResponse:
    """Create a new user account with default storage quota."""
    user = await AuthService.register(db, user_in)
    return UserResponse.model_validate(user)


@router.post("/login", response_model=Token, summary="User Login (JSON)", dependencies=[Depends(auth_rate_limiter)])
async def login_json(
    credentials: UserLogin,
    db: SessionDep,
) -> Token:
    """Authenticate with JSON payload and receive JWT access token."""
    user = await AuthService.authenticate(db, credentials.email, credentials.password)
    access_token = create_access_token(subject=user.id)
    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/login/form", response_model=Token, summary="OAuth2 Compatible Login (Swagger UI)", dependencies=[Depends(auth_rate_limiter)])
async def login_form(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: SessionDep,
) -> Token:
    """Authenticate with OAuth2 form data (for Swagger UI interactive documentation)."""
    user = await AuthService.authenticate(db, form_data.username, form_data.password)
    access_token = create_access_token(subject=user.id)
    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get("/me", response_model=UserResponse, summary="Get Current User Profile")
async def get_current_user_profile(
    current_user: CurrentUserDep,
    db: SessionDep,
) -> UserResponse:
    """Retrieve details and storage usage for the authenticated user."""
    actual_used = await AuthService.calculate_user_storage_used(db, current_user.id)
    if current_user.storage_used_bytes != actual_used:
        current_user.storage_used_bytes = actual_used
        await db.commit()
        await db.refresh(current_user)
    return UserResponse.model_validate(current_user)


@router.delete("/me", response_model=MessageResponse, summary="Delete Current User Account")
async def delete_current_user_account(
    current_user: CurrentUserDep,
    db: SessionDep,
    storage: StorageDep,
) -> MessageResponse:
    """Permanently delete authenticated user account and all associated files, folders, and shares."""
    await AuthService.delete_user_account(db, current_user, storage)
    return MessageResponse(message="Account and all associated data permanently deleted")



@router.get("/quota", response_model=UserQuotaResponse, summary="Get Storage Quota Status")
async def get_storage_quota(
    current_user: CurrentUserDep,
    db: SessionDep,
) -> UserQuotaResponse:
    """Retrieve real-time storage quota usage and available bytes."""
    return await AuthService.get_quota_details(db, current_user)


@router.post(
    "/forgot-password/send-otp",
    response_model=ForgotPasswordResponse,
    summary="Send Password Reset OTP (Valid for 5 minutes)",
    dependencies=[Depends(otp_rate_limiter)],
)
async def send_forgot_password_otp(
    payload: ForgotPasswordRequest,
    db: SessionDep,
) -> ForgotPasswordResponse:
    _, raw_otp, delivered, delivery_error = await AuthService.request_password_reset_otp(db, payload.email)
    debug_otp = raw_otp if (settings.DEBUG or settings.ENVIRONMENT == "development" or not delivered) else None

    if delivered:
        message = "A 6-digit verification code has been sent to your email. It is valid for 5 minutes."
    else:
        message = (
            f"Notice: Email could not be delivered via AWS SES ({delivery_error or 'unverified identity/sandbox'}). "
            f"Your 6-digit verification code is: {raw_otp}"
        )

    return ForgotPasswordResponse(
        message=message,
        expires_in_seconds=300,
        debug_otp=debug_otp,
        delivered=delivered,
        delivery_warning=delivery_error if not delivered else None,
    )


@router.post(
    "/forgot-password/reset",
    response_model=ResetPasswordResponse,
    summary="Reset Password with OTP",
    dependencies=[Depends(otp_rate_limiter)],
)
async def reset_password_with_otp(
    payload: ResetPasswordRequest,
    db: SessionDep,
) -> ResetPasswordResponse:
    """Reset user password using the 6-digit verification code sent to email."""
    await AuthService.reset_password_with_otp(
        db=db,
        email=payload.email,
        new_password=payload.new_password,
        confirm_password=payload.confirm_password,
        otp=payload.otp,
    )
    return ResetPasswordResponse(
        message="Password has been successfully reset. You can now log in with your new password."
    )

