from typing import AsyncGenerator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.logging import logger

# Engine configuration
engine_kwargs = {
    "echo": False,
    "future": True,
}

if settings.USE_NULL_POOL or "sqlite" in settings.DATABASE_URL:
    # Use NullPool when deployed behind AWS RDS Proxy or in serverless environments
    if "sqlite" not in settings.DATABASE_URL:
        engine_kwargs["poolclass"] = NullPool
else:
    engine_kwargs.update({
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_timeout": settings.DB_POOL_TIMEOUT,
        "pool_recycle": settings.DB_POOL_RECYCLE,
        "pool_pre_ping": settings.DB_POOL_PRE_PING,
    })

async_engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)

async_session_factory = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)

_db_initialized = False


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Dependency providing an async database session per request."""
    global _db_initialized
    async with async_session_factory() as session:
        if not _db_initialized:
            try:
                if "postgresql" in settings.DATABASE_URL:
                    await session.execute(text("""
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
                    await session.execute(text("CREATE INDEX IF NOT EXISTS ix_password_reset_otps_email ON password_reset_otps (email);"))
                    await session.execute(text("ALTER TABLE folders DROP CONSTRAINT IF EXISTS uq_owner_parent_folder_name;"))
                    await session.commit()
                _db_initialized = True
            except Exception as e:
                logger.warning(f"Auto-init check in get_db: {e}")
                await session.rollback()

        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

