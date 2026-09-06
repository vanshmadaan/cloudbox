from typing import Any, Dict
from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import SessionDep, StorageDep
from app.core.config import settings

router = APIRouter()


@router.get("/health", summary="Health Check")
async def health_check(
    db: SessionDep,
    storage: StorageDep,
) -> Dict[str, Any]:
    """
    Service health probe: checks database connectivity and storage configuration.
    """
    db_status = "healthy"
    try:
        await db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"

    return {
        "status": "online" if db_status == "healthy" else "degraded",
        "app": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "database": db_status,
        "storage_backend": settings.STORAGE_BACKEND,
    }

