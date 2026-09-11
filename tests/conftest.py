import asyncio
import os
import shutil
import tempfile
from typing import AsyncGenerator
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_db, get_queue_service, get_storage_backend
from app.core.config import settings
from app.db.base import Base
from app.main import app
from app.models.user import User
from app.services.queue_service import QueueService
from app.storage.local import LocalStorageBackend

# Use an in-memory SQLite database and disable rate limiting for test suite
settings.ENVIRONMENT = "test"
settings.RATE_LIMIT_ENABLED = False
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

TestingSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create a fresh database schema for each test."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestingSessionLocal() as session:
        yield session
        await session.rollback()

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(scope="function")
def temp_storage_dir():
    temp_dir = tempfile.mkdtemp(prefix="cloudstorage_test_")
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture(scope="function")
def mock_storage(temp_storage_dir):
    return LocalStorageBackend(base_dir=temp_storage_dir)


@pytest.fixture(scope="function")
def mock_queue():
    return QueueService(queue_url=None)


@pytest_asyncio.fixture(scope="function")
async def client(
    db_session: AsyncSession,
    mock_storage: LocalStorageBackend,
    mock_queue: QueueService,
) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP test client with dependency overrides."""
    async def override_get_db():
        yield db_session

    def override_storage():
        return mock_storage

    def override_queue():
        return mock_queue

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_storage_backend] = override_storage
    app.dependency_overrides[get_queue_service] = override_queue

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def auth_headers(client: AsyncClient) -> dict:
    """Register and authenticate a primary test user."""
    user_data = {
        "email": "primary_user@example.com",
        "password": "SecretPassword123!",
        "full_name": "Primary User",
    }
    signup_resp = await client.post("/api/v1/auth/signup", json=user_data)
    assert signup_resp.status_code == 201

    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": user_data["email"], "password": user_data["password"]},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="function")
async def secondary_auth_headers(client: AsyncClient) -> dict:
    """Register and authenticate a secondary test user for isolation checks."""
    user_data = {
        "email": "secondary_user@example.com",
        "password": "AnotherSecret123!",
        "full_name": "Secondary User",
    }
    signup_resp = await client.post("/api/v1/auth/signup", json=user_data)
    assert signup_resp.status_code == 201

    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": user_data["email"], "password": user_data["password"]},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

