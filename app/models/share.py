from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import TimeStampedModel

if TYPE_CHECKING:
    from app.models.file import File
    from app.models.folder import Folder
    from app.models.user import User


class SharedLink(TimeStampedModel):
    """
    Public or password-less shareable link for files and folders.
    Supports permission levels and TTL expiration.
    """
    __tablename__ = "shared_links"

    share_token: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=False
    )
    file_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("files.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    folder_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("folders.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    created_by_user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Permission: "view", "download"
    permission: Mapped[str] = mapped_column(String(32), default="download", nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    access_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    created_by: Mapped["User"] = relationship("User", back_populates="shared_links", lazy="selectin")
    file: Mapped[Optional["File"]] = relationship("File", back_populates="shared_links", lazy="selectin")
    folder: Mapped[Optional["Folder"]] = relationship("Folder", back_populates="shared_links", lazy="selectin")

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        exp = self.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > exp

