from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import TimeStampedModel

if TYPE_CHECKING:
    from app.models.blob import ContentBlob
    from app.models.folder import Folder
    from app.models.share import SharedLink
    from app.models.user import User


class File(TimeStampedModel):
    """
    Logical file entity representing a user's file.
    Directly references a ContentBlob and supports soft-delete retention.
    """
    __tablename__ = "files"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    folder_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("folders.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    owner_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    blob_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("content_blobs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="READY", nullable=False)
    thumbnail_s3_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    owner: Mapped["User"] = relationship("User", back_populates="files")
    folder: Mapped[Optional["Folder"]] = relationship("Folder", back_populates="files")
    blob: Mapped["ContentBlob"] = relationship("ContentBlob", back_populates="files", lazy="selectin")
    shared_links: Mapped[List["SharedLink"]] = relationship(
        "SharedLink",
        back_populates="file",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    def days_until_purge(self, retention_days: int = 14) -> int:
        if not self.is_deleted or not self.deleted_at:
            return retention_days
        d_at = self.deleted_at
        if d_at.tzinfo is None:
            d_at = d_at.replace(tzinfo=timezone.utc)
        elapsed = datetime.now(timezone.utc) - d_at
        remaining = retention_days - elapsed.days
        return max(0, remaining)

    def is_purge_due(self, retention_days: int = 14) -> bool:
        if not self.is_deleted or not self.deleted_at:
            return False
        d_at = self.deleted_at
        if d_at.tzinfo is None:
            d_at = d_at.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= (d_at + timedelta(days=retention_days))

