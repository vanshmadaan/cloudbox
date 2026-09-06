from typing import TYPE_CHECKING, List
from sqlalchemy import BigInteger, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import TimeStampedModel

if TYPE_CHECKING:
    from app.models.file import File


class ContentBlob(TimeStampedModel):
    """
    Content-Addressable Storage Blob.
    Enables hash-based deduplication across all users and files.
    """
    __tablename__ = "content_blobs"

    # SHA-256 hash of the file bytes
    checksum_sha256: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=False
    )
    # Physical S3 object key (e.g. blobs/ab/cd/abcdef123...)
    s3_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(255),
        default="application/octet-stream",
        nullable=False
    )
    # Reference counting to safely prune unreferenced S3 objects
    ref_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Relationships
    files: Mapped[List["File"]] = relationship(
        "File",
        back_populates="blob",
        lazy="selectin"
    )

