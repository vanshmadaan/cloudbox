import datetime
import hashlib
import hmac
import secrets
from datetime import timedelta, timezone
from typing import Optional, Tuple
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthenticationError, ConflictError, NotFoundError, ValidationError
from app.core.logging import logger
from app.core.security import get_password_hash, verify_password
from app.db.base import Base
from app.storage.base import StorageBackend
from app.models.file import File
from app.models.folder import Folder
from app.models.password_reset_otp import PasswordResetOtp
from app.models.share import SharedLink
from app.models.user import User
from app.schemas.auth import UserCreate, UserQuotaResponse
from app.services.email_service import EmailService


class AuthService:
    """Business logic for user registration, authentication, and quota tracking."""

    @staticmethod
    async def register(db: AsyncSession, user_in: UserCreate) -> User:
        result = await db.execute(select(User).where(User.email == user_in.email))
        existing_user = result.scalar_one_or_none()
        if existing_user:
            raise ConflictError(
                message=f"User with email '{user_in.email}' already exists",
                code="USER_ALREADY_EXISTS",
            )

        hashed_password = get_password_hash(user_in.password)
        db_user = User(
            email=user_in.email,
            hashed_password=hashed_password,
            full_name=user_in.full_name,
            storage_quota_bytes=settings.DEFAULT_STORAGE_QUOTA_BYTES,
            storage_used_bytes=0,
            is_active=True,
            is_superuser=False,
        )
        db.add(db_user)
        await db.commit()
        await db.refresh(db_user)
        return db_user

    @staticmethod
    async def authenticate(db: AsyncSession, email: str, password: str) -> User:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if not user:
            raise AuthenticationError(message="Invalid email or password")
        if not verify_password(password, user.hashed_password):
            raise AuthenticationError(message="Invalid email or password")
        if not user.is_active:
            raise AuthenticationError(message="User account is inactive", code="USER_INACTIVE")
        return user

    @staticmethod
    async def get_by_id(db: AsyncSession, user_id: str) -> User:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise NotFoundError("User", user_id)
        return user

    @staticmethod
    async def calculate_user_storage_used(db: AsyncSession, user_id: str) -> int:
        """
        Calculate actual active storage used by all non-deleted files owned by the user
        whose parent folders (and ancestors) are not in trash.
        """
        # 1. Query all non-deleted files
        f_res = await db.execute(
            select(File).where(
                File.owner_id == user_id,
                File.is_deleted.is_(False),
            )
        )
        active_files = list(f_res.scalars().all())
        if not active_files:
            return 0

        # 2. Query all folders for this user to check ancestral deletion status
        folder_res = await db.execute(
            select(Folder.id, Folder.parent_id, Folder.is_deleted).where(
                Folder.owner_id == user_id
            )
        )
        folder_map = {row.id: (row.parent_id, row.is_deleted) for row in folder_res.all()}

        def is_in_trash(folder_id: Optional[str]) -> bool:
            curr = folder_id
            visited = set()
            while curr:
                if curr in visited or curr not in folder_map:
                    break
                visited.add(curr)
                parent_id, is_del = folder_map[curr]
                if is_del:
                    return True
                curr = parent_id
            return False

        total_bytes = 0
        for f in active_files:
            if not f.folder_id or not is_in_trash(f.folder_id):
                total_bytes += f.file_size

        return total_bytes

    @staticmethod
    async def get_quota_details(db: AsyncSession, user: User) -> UserQuotaResponse:
        # Self-healing sync: update storage_used_bytes with real-time active storage in database
        actual_used = await AuthService.calculate_user_storage_used(db, user.id)
        if user.storage_used_bytes != actual_used:
            user.storage_used_bytes = actual_used
            await db.commit()
            await db.refresh(user)

        quota = user.storage_quota_bytes
        used = user.storage_used_bytes
        avail = max(0, quota - used)
        percentage = round((used / quota * 100), 2) if quota > 0 else 100.0
        return UserQuotaResponse(
            storage_quota_bytes=quota,
            storage_used_bytes=used,
            storage_available_bytes=avail,
            storage_used_percentage=percentage,
        )

    @staticmethod
    async def _ensure_otp_table_exists(db: AsyncSession):
        """Ensure password_reset_otps table exists even in serverless environments without lifespan."""
        try:
            if "postgresql" in settings.DATABASE_URL:
                await db.execute(text("""
                    CREATE TABLE IF NOT EXISTS password_reset_otps (
                        id VARCHAR(36) PRIMARY KEY,
                        email VARCHAR(255) NOT NULL,
                        otp_hash VARCHAR(255) NOT NULL,
                        expires_at TIMESTAMPTZ NOT NULL,
                        attempts INTEGER NOT NULL DEFAULT 0,
                        is_used BOOLEAN NOT NULL DEFAULT FALSE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                """))
                await db.execute(text("CREATE INDEX IF NOT EXISTS ix_password_reset_otps_email ON password_reset_otps (email);"))
                await db.commit()
            elif "sqlite" in settings.DATABASE_URL:
                conn = await db.connection()
                await conn.run_sync(Base.metadata.create_all)
        except Exception as e:
            logger.warning(f"Auto-create password_reset_otps table check: {e}")
            await db.rollback()

    @staticmethod
    async def request_password_reset_otp(
        db: AsyncSession, email: str
    ) -> Tuple[PasswordResetOtp, str, bool, Optional[str]]:
        """Generate and dispatch a 6-digit OTP valid for 5 minutes."""
        await AuthService._ensure_otp_table_exists(db)
        email_clean = email.lower().strip()
        result = await db.execute(select(User).where(User.email == email_clean))
        user = result.scalar_one_or_none()
        if not user:
            raise NotFoundError("User", email, message="No account found with this email address")
        if not user.is_active:
            raise AuthenticationError(message="User account is inactive", code="USER_INACTIVE")

        # Invalidate any existing unused OTPs for this email
        existing_res = await db.execute(
            select(PasswordResetOtp).where(
                PasswordResetOtp.email == email_clean,
                PasswordResetOtp.is_used.is_(False),
            )
        )
        for old_record in existing_res.scalars().all():
            old_record.is_used = True

        # Generate cryptographically secure 6-digit numeric OTP
        raw_otp = f"{secrets.randbelow(1000000):06d}"
        otp_hash = hmac.new(
            settings.SECRET_KEY.encode(),
            f"{email_clean}:{raw_otp}".encode(),
            hashlib.sha256,
        ).hexdigest()

        now = datetime.datetime.now(timezone.utc)
        otp_record = PasswordResetOtp(
            email=email_clean,
            otp_hash=otp_hash,
            expires_at=now + timedelta(minutes=5),
            attempts=0,
            is_used=False,
        )
        db.add(otp_record)
        await db.commit()
        await db.refresh(otp_record)

        # Dispatch email
        delivered, delivery_error = await EmailService.send_password_reset_otp(email_clean, raw_otp)
        return otp_record, raw_otp, delivered, delivery_error

    @staticmethod
    async def reset_password_with_otp(
        db: AsyncSession,
        email: str,
        new_password: str,
        confirm_password: str,
        otp: str,
    ) -> User:
        """Verify 5-minute OTP and update user password."""
        await AuthService._ensure_otp_table_exists(db)
        email_clean = email.lower().strip()
        otp_clean = otp.strip()

        if new_password != confirm_password:
            raise ValidationError(message="New password and confirm password do not match")

        if len(new_password) < 6:
            raise ValidationError(message="Password must be at least 6 characters")

        # Find latest unused OTP for this email
        res = await db.execute(
            select(PasswordResetOtp)
            .where(PasswordResetOtp.email == email_clean, PasswordResetOtp.is_used.is_(False))
            .order_by(PasswordResetOtp.created_at.desc())
        )
        otp_record = res.scalars().first()
        if not otp_record:
            user_check = await db.execute(select(User).where(User.email == email_clean))
            if not user_check.scalar_one_or_none():
                raise NotFoundError("User", email, message="No account found with this email address")

            raise AuthenticationError(
                message="No active OTP found. Please click 'Send OTP' to request a verification code.",
                code="INVALID_OTP",
            )

        # Verify 5-minute expiration
        now = datetime.datetime.now(timezone.utc)
        expires_at = otp_record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if now > expires_at:
            otp_record.is_used = True
            await db.commit()
            raise AuthenticationError(
                message="OTP has expired. Verification codes are valid for 5 minutes only. Please request a new OTP.",
                code="OTP_EXPIRED",
            )

        # Rate limiting: max 5 attempts per OTP
        if otp_record.attempts >= 5:
            otp_record.is_used = True
            await db.commit()
            raise AuthenticationError(
                message="Too many failed attempts. This OTP has been invalidated. Please request a new OTP.",
                code="OTP_MAX_ATTEMPTS",
            )

        # Verify OTP hash
        expected_hash = hmac.new(
            settings.SECRET_KEY.encode(),
            f"{email_clean}:{otp_clean}".encode(),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected_hash, otp_record.otp_hash):
            otp_record.attempts += 1
            await db.commit()
            remaining = max(0, 5 - otp_record.attempts)
            raise AuthenticationError(
                message=f"Invalid verification code. {remaining} attempt(s) remaining.",
                code="INVALID_OTP",
            )

        # Mark OTP as successfully used
        otp_record.is_used = True

        # Fetch user and update password
        user_res = await db.execute(select(User).where(User.email == email_clean))
        user = user_res.scalar_one_or_none()
        if not user:
            raise NotFoundError("User", email_clean)

        user.hashed_password = get_password_hash(new_password)
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def delete_user_account(
        db: AsyncSession,
        user: User,
        storage: StorageBackend,
    ) -> None:
        """
        Permanently delete user account and all associated data:
        1. Deletes all user files and prunes unreferenced S3 blobs & thumbnails.
        2. Deletes all user folders.
        3. Deletes any shared links created by the user.
        4. Deletes any password reset OTPs.
        5. Deletes the user entity.
        """
        owner_id = user.id

        # 1. Clean up S3 storage objects for user's files
        files_res = await db.execute(select(File).where(File.owner_id == owner_id))
        files = files_res.scalars().all()

        blobs_to_delete = []
        for file_obj in files:
            blob = file_obj.blob
            if blob:
                blob.ref_count -= 1
                if blob.ref_count <= 0:
                    try:
                        await storage.delete_object(blob.s3_key)
                    except Exception as e:
                        logger.warning(f"Failed to delete unreferenced S3 blob {blob.s3_key}: {e}")
                    blobs_to_delete.append(blob)

            if file_obj.thumbnail_s3_key:
                try:
                    await storage.delete_object(file_obj.thumbnail_s3_key)
                except Exception as e:
                    logger.warning(f"Failed to delete thumbnail {file_obj.thumbnail_s3_key}: {e}")

        for b in blobs_to_delete:
            await db.delete(b)

        # 2. Delete OTP records for user's email
        await db.execute(delete(PasswordResetOtp).where(PasswordResetOtp.email == user.email))

        # 3. Delete User entity (cascades to files, folders, and shared_links)
        await db.delete(user)
        await db.commit()
        logger.info(f"User account {owner_id} ({user.email}) permanently deleted.")


