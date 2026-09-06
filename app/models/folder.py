from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import TimeStampedModel

if TYPE_CHECKING:
    from app.models.file import File
    from app.models.share import SharedLink
    from app.models.user import User


class Folder(TimeStampedModel):
    """
    Hierarchical folder model with self-referential parent/children tree.
    """
    __tablename__ = "folders"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_id: Mapped[Optional[str]] = mapped_column(
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
    path: Mapped[str] = mapped_column(String(1024), default="/", nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    owner: Mapped["User"] = relationship("User", back_populates="folders")
    parent: Mapped[Optional["Folder"]] = relationship(
        "Folder",
        remote_side="Folder.id",
        back_populates="children",
        lazy="selectin"
    )
    children: Mapped[List["Folder"]] = relationship(
        "Folder",
        back_populates="parent",
        cascade="all, delete-orphan",
        lazy="selectin"
    )
    files: Mapped[List["File"]] = relationship(
        "File",
        back_populates="folder",
        cascade="all, delete-orphan",
        lazy="selectin"
    )
    shared_links: Mapped[List["SharedLink"]] = relationship(
        "SharedLink",
        back_populates="folder",
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

