import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse as FastAPIFileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from mangum import Mangum
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.api import api_router
from app.core.config import settings
from app.core.exceptions import AppException
from app.core.logging import logger, setup_logging
from app.db.base import Base
from app.db.session import async_engine

# Path to frontend static files
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


from sqlalchemy import text


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager for startup and shutdown hooks."""
    setup_logging(debug=settings.DEBUG)
    logger.info(f"Starting {settings.PROJECT_NAME} v{settings.VERSION} [{settings.ENVIRONMENT}]")

    # Initialize and auto-migrate tables
    try:
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Auto-migrate newly added columns and tables for existing PostgreSQL databases
            if "postgresql" in settings.DATABASE_URL:
                await conn.execute(text("ALTER TABLE folders ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE;"))
                await conn.execute(text("ALTER TABLE folders ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;"))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_folders_is_deleted ON folders (is_deleted);"))
                await conn.execute(text("ALTER TABLE folders DROP CONSTRAINT IF EXISTS uq_owner_parent_folder_name;"))
                await conn.execute(text("ALTER TABLE files ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE;"))
                await conn.execute(text("ALTER TABLE files ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;"))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_files_is_deleted ON files (is_deleted);"))
                await conn.execute(text("ALTER TABLE files ADD COLUMN IF NOT EXISTS blob_id VARCHAR(36) REFERENCES content_blobs(id);"))
                await conn.execute(text("ALTER TABLE files ADD COLUMN IF NOT EXISTS file_size BIGINT DEFAULT 0;"))
                await conn.execute(text("ALTER TABLE files ADD COLUMN IF NOT EXISTS checksum_sha256 VARCHAR(64) DEFAULT '';"))
                await conn.execute(text("ALTER TABLE files ADD COLUMN IF NOT EXISTS status VARCHAR(32) DEFAULT 'READY';"))
                await conn.execute(text("ALTER TABLE files ADD COLUMN IF NOT EXISTS thumbnail_s3_key VARCHAR(512);"))
                await conn.execute(text("""
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
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_password_reset_otps_email ON password_reset_otps (email);"))
        logger.info("Database tables initialized and migrated successfully.")
    except Exception as e:
        logger.warning(f"Could not auto-create/migrate database tables on startup: {e}")

    yield

    logger.info("Shutting down Cloud Storage Backend...")
    await async_engine.dispose()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
    lifespan=lifespan,
)


# --- Middlewares ---

# 1. Stage Prefix Stripping Middleware (for AWS API Gateway stages like /prod)
class StripStageMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path == "/prod":
                scope["path"] = "/"
            elif path.startswith("/prod/"):
                scope["path"] = path[5:]
        await self.app(scope, receive, send)

app.add_middleware(StripStageMiddleware)


# 2. CORS Middleware
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# 2. Request Logging & Timing Middleware
@app.middleware("http")
async def log_requests_middleware(request: Request, call_next):
    start_time = time.time()
    path = request.url.path
    method = request.method

    try:
        response = await call_next(request)
        duration_ms = round((time.time() - start_time) * 1000, 2)
        logger.info(
            f"{method} {path} - {response.status_code} ({duration_ms}ms)"
        )
        return response
    except Exception as exc:
        duration_ms = round((time.time() - start_time) * 1000, 2)
        logger.error(
            f"{method} {path} - FAILED with error: {str(exc)} ({duration_ms}ms)"
        )
        raise exc


# --- Exception Handlers ---

@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Handle custom application domain exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict(),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle Pydantic request validation errors."""
    errors = []
    for err in exc.errors():
        field = " -> ".join(str(loc) for loc in err.get("loc", []))
        msg = err.get("msg")
        errors.append({"field": field, "message": msg})

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": errors[0]["message"] if errors else "Invalid request parameters",
                "details": errors,
            }
        },
    )


@app.exception_handler(StarletteHTTPException)
async def starlette_http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Handle Starlette HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": f"HTTP_{exc.status_code}",
                "message": exc.detail,
            }
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all unexpected internal server errors."""
    logger.exception(f"Unhandled exception on {request.method} {request.url.path}: {str(exc)}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected internal server error occurred.",
            }
        },
    )


# --- Route Mounts ---

# Mount API routes
app.include_router(api_router, prefix=settings.API_V1_STR)

# Root level redirects for Swagger UI and ReDoc
@app.get("/docs", include_in_schema=False)
async def redirect_docs():
    """Redirect /docs to versioned docs URL."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"{settings.API_V1_STR}/docs")


@app.get("/redoc", include_in_schema=False)
async def redirect_redoc():
    """Redirect /redoc to versioned redoc URL."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"{settings.API_V1_STR}/redoc")


@app.get("/openapi.json", include_in_schema=False)
async def redirect_openapi():
    """Redirect /openapi.json to versioned openapi.json URL."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"{settings.API_V1_STR}/openapi.json")


# Mount Static frontend assets if directory exists
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_index():
        return FastAPIFileResponse(str(STATIC_DIR / "index.html"))


# --- AWS Lambda / API Gateway Handler ---
# Mangum translates API Gateway HTTP events into ASGI requests for FastAPI
handler = Mangum(app, lifespan="off")

