import json
from typing import Any, List, Optional, Union
from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # General App Settings
    PROJECT_NAME: str = "Cloud Storage Backend"
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    API_V1_STR: str = "/api/v1"

    # Security & JWT
    SECRET_KEY: str = "insecure-default-change-me-in-production-1234567890"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # Database Configuration (PostgreSQL with asyncpg)
    DATABASE_URL: str = "postgresql+asyncpg://clouduser:vnsh77@localhost:5432/cloudstorage"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 300
    DB_POOL_PRE_PING: bool = True
    USE_NULL_POOL: bool = False  # Set to True when using AWS RDS Proxy / Lambda

    # Quota Settings (Default: 100 MB per user)
    DEFAULT_STORAGE_QUOTA_BYTES: int = 100 * 1024 * 1024

    # AWS S3 Settings
    AWS_REGION: str = "us-east-1"
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_SESSION_TOKEN: Optional[str] = None
    S3_BUCKET_NAME: str = "cloud-storage-bucket"
    S3_PRESIGNED_EXPIRATION_SECONDS: int = 3600  # 1 hour
    S3_ENDPOINT_URL: Optional[str] = None  # For LocalStack/MinIO

    # AWS SQS Settings (Background Worker)
    SQS_QUEUE_URL: Optional[str] = None
    SQS_ENDPOINT_URL: Optional[str] = None

    # Storage Backend Selection: "local" (default for offline/dev) or "s3" (production / AWS)
    STORAGE_BACKEND: str = "local"
    LOCAL_STORAGE_DIR: str = "./data/storage"

    # Email & AWS SES Settings
    SES_SENDER_EMAIL: str = "noreply@cloudbox.com"
    EMAILS_ENABLED: bool = True

    # CORS
    BACKEND_CORS_ORIGINS: Union[List[str], str] = ["*"]

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            if not v.startswith("["):
                return [i.strip() for i in v.split(",") if i.strip()]
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                pass
        elif isinstance(v, list):
            return v
        return ["*"]


settings = Settings()

