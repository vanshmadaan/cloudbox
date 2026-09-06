import pytest
from httpx import AsyncClient
from sqlalchemy import update
from app.models.user import User


@pytest.fixture
async def admin_auth_headers(client: AsyncClient, db_session) -> dict:
    """Create and return headers for an admin/superuser."""
    email = "admin_user@example.com"
    password = "AdminPassword123"

    # Signup
    await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password, "full_name": "Admin Boss"},
    )

    # Elevate to superuser in DB
    await db_session.execute(
        update(User).where(User.email == email).values(is_superuser=True)
    )
    await db_session.commit()

    # Login
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    token = login_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_admin_endpoints_forbidden_for_normal_users(client: AsyncClient, auth_headers: dict):
    # Standard user tries to access admin stats
    resp = await client.get("/api/v1/admin/stats", headers=auth_headers)
    assert resp.status_code == 403

    # Standard user tries to list users
    resp2 = await client.get("/api/v1/admin/users", headers=auth_headers)
    assert resp2.status_code == 403


@pytest.mark.asyncio
async def test_admin_get_stats(client: AsyncClient, admin_auth_headers: dict):
    resp = await client.get("/api/v1/admin/stats", headers=admin_auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "total_users" in data
    assert data["total_users"] >= 1
    assert "total_storage_used_bytes" in data
    assert "total_files" in data


@pytest.mark.asyncio
async def test_admin_list_and_search_users(client: AsyncClient, admin_auth_headers: dict):
    # Create another regular user
    reg_email = "regular_target@example.com"
    await client.post(
        "/api/v1/auth/signup",
        json={"email": reg_email, "password": "TargetPassword123", "full_name": "Target User"},
    )

    # Admin lists users
    resp = await client.get("/api/v1/admin/users", headers=admin_auth_headers)
    assert resp.status_code == 200
    users = resp.json()
    emails = [u["email"] for u in users]
    assert reg_email in emails

    # Search for specific user
    resp_search = await client.get(
        "/api/v1/admin/users?search=regular_target", headers=admin_auth_headers
    )
    assert resp_search.status_code == 200
    matched = resp_search.json()
    assert len(matched) == 1
    assert matched[0]["email"] == reg_email


@pytest.mark.asyncio
async def test_admin_update_user_quota_and_status(client: AsyncClient, admin_auth_headers: dict, db_session):
    reg_email = "quota_user@example.com"
    signup_resp = await client.post(
        "/api/v1/auth/signup",
        json={"email": reg_email, "password": "UserPass123", "full_name": "Quota Guy"},
    )
    user_id = signup_resp.json()["id"]

    # 1. Update quota to 500 MB (524,288,000 bytes)
    new_quota = 524288000
    patch_resp = await client.patch(
        f"/api/v1/admin/users/{user_id}",
        json={"storage_quota_bytes": new_quota},
        headers=admin_auth_headers,
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["storage_quota_bytes"] == new_quota

    # 2. Deactivate user
    deact_resp = await client.patch(
        f"/api/v1/admin/users/{user_id}",
        json={"is_active": False},
        headers=admin_auth_headers,
    )
    assert deact_resp.status_code == 200
    assert deact_resp.json()["is_active"] is False

    # Verify deactivated user cannot log in
    login_attempt = await client.post(
        "/api/v1/auth/login",
        json={"email": reg_email, "password": "UserPass123"},
    )
    assert login_attempt.status_code in (401, 403)

    # 3. Reactivate user
    react_resp = await client.patch(
        f"/api/v1/admin/users/{user_id}",
        json={"is_active": True},
        headers=admin_auth_headers,
    )
    assert react_resp.status_code == 200
    assert react_resp.json()["is_active"] is True
