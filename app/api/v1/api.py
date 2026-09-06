from fastapi import APIRouter

from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.files import router as files_router
from app.api.v1.endpoints.folders import router as folders_router
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.shares import router as shares_router
from app.api.v1.endpoints.admin import router as admin_router

api_router = APIRouter()

api_router.include_router(health_router, tags=["Health"])
api_router.include_router(auth_router, prefix="/auth", tags=["Authentication"])
api_router.include_router(folders_router, prefix="/folders", tags=["Folders"])
api_router.include_router(files_router, prefix="/files", tags=["Files"])
api_router.include_router(shares_router, prefix="/shares", tags=["Sharing"])
api_router.include_router(admin_router, prefix="/admin", tags=["Admin"])

