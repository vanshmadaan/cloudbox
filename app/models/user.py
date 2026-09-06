from typing import TYPE_CHECKING, List
from sqlalchemy import BigInteger, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import TimeStampedModel

if TYPE_CHECKING:
    from app.models.file import File
    from app.models.folder import Folder
    from app.models.share import SharedLink


class User(TimeStampedModel):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=True)

    # Storage Quota in Bytes (default 100MB)
    storage_quota_bytes: Mapped[int] = mapped_column(
        BigInteger,
        default=104857600,  # 100 MB
        nullable=False
    )
    storage_used_bytes: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
        nullable=False
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    folders: Mapped[List["Folder"]] = relationship(
        "Folder",
        back_populates="owner",
        cascade="all, delete-orphan",
        lazy="selectin"
    )
    files: Mapped[List["File"]] = relationship(
        "File",
        back_populates="owner",
        cascade="all, delete-orphan",
        lazy="selectin"
    )
    shared_links: Mapped[List["SharedLink"]] = relationship(
        "SharedLink",
        back_populates="created_by",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    @property
    def storage_used_percentage(self) -> float:
        if self.storage_quota_bytes > 0:
            return round((self.storage_used_bytes / self.storage_quota_bytes) * 100, 2)
        return 100.0

