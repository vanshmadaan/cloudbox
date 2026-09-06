import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_signup_success(client: AsyncClient):
    response = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": "test_new@example.com",
            "password": "Password123!",
            "full_name": "Test User",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "test_new@example.com"
    assert data["full_name"] == "Test User"
    assert "id" in data
    assert "hashed_password" not in data
    assert data["storage_quota_bytes"] > 0
    assert data["storage_used_bytes"] == 0


@pytest.mark.asyncio
async def test_signup_duplicate_email(client: AsyncClient):
    user_payload = {
        "email": "duplicate@example.com",
        "password": "Password123!",
        "full_name": "Duplicate User",
    }
    resp1 = await client.post("/api/v1/auth/signup", json=user_payload)
    assert resp1.status_code == 201

    resp2 = await client.post("/api/v1/auth/signup", json=user_payload)
    assert resp2.status_code == 409
    data = resp2.json()
    assert data["error"]["code"] == "USER_ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_signup_missing_full_name(client: AsyncClient):
    # Missing full_name field
    response = await client.post(
        "/api/v1/auth/signup",
        json={"email": "missing_name@example.com", "password": "Password123!"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_signup_empty_or_whitespace_full_name(client: AsyncClient):
    # Empty full_name
    res_empty = await client.post(
        "/api/v1/auth/signup",
        json={"email": "empty_name@example.com", "password": "Password123!", "full_name": ""},
    )
    assert res_empty.status_code == 422

    # Whitespace-only full_name
    res_whitespace = await client.post(
        "/api/v1/auth/signup",
        json={"email": "white_name@example.com", "password": "Password123!", "full_name": "    "},
    )
    assert res_whitespace.status_code == 422


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient):
    # Create user
    await client.post(
        "/api/v1/auth/signup",
        json={"email": "login_user@example.com", "password": "ValidPassword123", "full_name": "Login User"},
    )
    # Login JSON
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "login_user@example.com", "password": "ValidPassword123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0


@pytest.mark.asyncio
async def test_login_invalid_password(client: AsyncClient):
    await client.post(
        "/api/v1/auth/signup",
        json={"email": "login_fail@example.com", "password": "CorrectPassword", "full_name": "Fail User"},
    )
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "login_fail@example.com", "password": "WrongPassword"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_login_oauth2_form(client: AsyncClient):
    await client.post(
        "/api/v1/auth/signup",
        json={"email": "form_user@example.com", "password": "Password123!", "full_name": "Form User"},
    )
    # Login via form
    response = await client.post(
        "/api/v1/auth/login/form",
        data={"username": "form_user@example.com", "password": "Password123!"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data


@pytest.mark.asyncio
async def test_current_user_profile_and_quota(client: AsyncClient, auth_headers: dict):
    # Test /me
    me_resp = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["email"] == "primary_user@example.com"

    # Test /quota
    quota_resp = await client.get("/api/v1/auth/quota", headers=auth_headers)
    assert quota_resp.status_code == 200
    quota_data = quota_resp.json()
    assert quota_data["storage_quota_bytes"] > 0
    assert quota_data["storage_used_bytes"] == 0
    assert quota_data["storage_available_bytes"] == quota_data["storage_quota_bytes"]
    assert quota_data["storage_used_percentage"] == 0.0


@pytest.mark.asyncio
async def test_forgot_password_send_otp_and_reset_flow(client: AsyncClient, db_session):
    # 1. Register a test user
    signup_resp = await client.post(
        "/api/v1/auth/signup",
        json={"email": "forgot_tester@example.com", "password": "OldPassword123!", "full_name": "Forgot Tester"},
    )
    assert signup_resp.status_code == 201

    # 2. Request OTP for password reset
    otp_resp = await client.post(
        "/api/v1/auth/forgot-password/send-otp",
        json={"email": "forgot_tester@example.com"},
    )
    assert otp_resp.status_code == 200
    otp_data = otp_resp.json()
    assert "verification code" in otp_data["message"]
    assert otp_data["expires_in_seconds"] == 300
    assert "debug_otp" in otp_data
    raw_otp = otp_data["debug_otp"]
    assert len(raw_otp) == 6

    # 3. Test wrong OTP rejection
    bad_otp_resp = await client.post(
        "/api/v1/auth/forgot-password/reset",
        json={
            "email": "forgot_tester@example.com",
            "new_password": "NewPassword123!",
            "confirm_password": "NewPassword123!",
            "otp": "000000" if raw_otp != "000000" else "111111",
        },
    )
    assert bad_otp_resp.status_code == 401
    assert "Invalid verification code" in bad_otp_resp.json()["error"]["message"]

    # 4. Test password mismatch rejection
    mismatch_resp = await client.post(
        "/api/v1/auth/forgot-password/reset",
        json={
            "email": "forgot_tester@example.com",
            "new_password": "NewPassword123!",
            "confirm_password": "DifferentPassword123!",
            "otp": raw_otp,
        },
    )
    assert mismatch_resp.status_code == 422
    assert "do not match" in mismatch_resp.json()["error"]["message"]

    # 5. Successful reset with valid OTP
    reset_resp = await client.post(
        "/api/v1/auth/forgot-password/reset",
        json={
            "email": "forgot_tester@example.com",
            "new_password": "NewPassword123!",
            "confirm_password": "NewPassword123!",
            "otp": raw_otp,
        },
    )
    assert reset_resp.status_code == 200
    assert "successfully reset" in reset_resp.json()["message"]

    # 6. Verify cannot reuse the same OTP
    reuse_resp = await client.post(
        "/api/v1/auth/forgot-password/reset",
        json={
            "email": "forgot_tester@example.com",
            "new_password": "AnotherPassword123!",
            "confirm_password": "AnotherPassword123!",
            "otp": raw_otp,
        },
    )
    assert reuse_resp.status_code == 401

    # 7. Old password no longer works
    old_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "forgot_tester@example.com", "password": "OldPassword123!"},
    )
    assert old_login.status_code == 401

    # 8. New password works successfully
    new_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "forgot_tester@example.com", "password": "NewPassword123!"},
    )
    assert new_login.status_code == 200
    assert "access_token" in new_login.json()


@pytest.mark.asyncio
async def test_forgot_password_nonexistent_email(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/forgot-password/send-otp",
        json={"email": "nonexistent_email_12345@example.com"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_forgot_password_expired_otp(client: AsyncClient, db_session):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select
    from app.models.password_reset_otp import PasswordResetOtp

    # Register user
    await client.post(
        "/api/v1/auth/signup",
        json={"email": "expired_otp_user@example.com", "password": "Password123!", "full_name": "Expired OTP User"},
    )

    # Send OTP
    otp_resp = await client.post(
        "/api/v1/auth/forgot-password/send-otp",
        json={"email": "expired_otp_user@example.com"},
    )
    raw_otp = otp_resp.json()["debug_otp"]

    # Fast-forward expiry in DB to 10 minutes in the past
    record_res = await db_session.execute(
        select(PasswordResetOtp).where(PasswordResetOtp.email == "expired_otp_user@example.com")
    )
    record = record_res.scalars().first()
    record.expires_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    await db_session.commit()

    # Attempt reset with expired OTP
    reset_resp = await client.post(
        "/api/v1/auth/forgot-password/reset",
        json={
            "email": "expired_otp_user@example.com",
            "new_password": "BrandNewPassword123!",
            "confirm_password": "BrandNewPassword123!",
            "otp": raw_otp,
        },
    )
    assert reset_resp.status_code == 401
    assert "expired" in reset_resp.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_forgot_password_random_otp_without_requesting_otp(client: AsyncClient):
    # 1. Existing user typing a random OTP without requesting OTP first
    await client.post(
        "/api/v1/auth/signup",
        json={"email": "existing_user_no_otp@example.com", "password": "Password123!", "full_name": "Existing User"},
    )

    resp = await client.post(
        "/api/v1/auth/forgot-password/reset",
        json={
            "email": "existing_user_no_otp@example.com",
            "new_password": "NewPassword123!",
            "confirm_password": "NewPassword123!",
            "otp": "999999",
        },
    )
    assert resp.status_code == 401
    assert "No active OTP found" in resp.json()["error"]["message"]

    # 2. Non-existent user typing a random OTP without requesting OTP first
    resp_nonexistent = await client.post(
        "/api/v1/auth/forgot-password/reset",
        json={
            "email": "nonexistent_reset_user@example.com",
            "new_password": "NewPassword123!",
            "confirm_password": "NewPassword123!",
            "otp": "999999",
        },
    )
    assert resp_nonexistent.status_code == 404
    assert "No account found with this email address" in resp_nonexistent.json()["error"]["message"]


@pytest.mark.asyncio
async def test_forgot_password_ses_fallback_delivery(client: AsyncClient, monkeypatch):
    from app.core.config import settings

    await client.post(
        "/api/v1/auth/signup",
        json={"email": "ses_fallback_user@example.com", "password": "Password123!", "full_name": "SES User"},
    )

    # Force EMAILS_ENABLED=False to simulate SES unconfigured / disabled
    monkeypatch.setattr(settings, "EMAILS_ENABLED", False)

    resp = await client.post(
        "/api/v1/auth/forgot-password/send-otp",
        json={"email": "ses_fallback_user@example.com"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["delivered"] is False
    assert data["debug_otp"] is not None
    assert "verification code" in data["message"].lower()

    # Verify reset works with the returned fallback OTP
    reset_resp = await client.post(
        "/api/v1/auth/forgot-password/reset",
        json={
            "email": "ses_fallback_user@example.com",
            "new_password": "NewSecretPassword123!",
            "confirm_password": "NewSecretPassword123!",
            "otp": data["debug_otp"],
        },
    )
    assert reset_resp.status_code == 200
    assert "successfully reset" in reset_resp.json()["message"]


@pytest.mark.asyncio
async def test_delete_user_account_success(client: AsyncClient):
    import io

    # 1. Sign up a new user
    signup_resp = await client.post(
        "/api/v1/auth/signup",
        json={"email": "delete_me@example.com", "password": "Password123!", "full_name": "To Delete"},
    )
    assert signup_resp.status_code == 201

    # 2. Log in and get headers
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "delete_me@example.com", "password": "Password123!"},
    )
    token = login_resp.json()["access_token"]
    user_headers = {"Authorization": f"Bearer {token}"}

    # 3. Create a folder and a file
    folder_resp = await client.post(
        "/api/v1/folders/",
        json={"name": "MyFolder"},
        headers=user_headers,
    )
    assert folder_resp.status_code == 201

    file_resp = await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("test_delete.txt", io.BytesIO(b"data to delete"), "text/plain")},
        headers=user_headers,
    )
    assert file_resp.status_code == 201

    # 4. Delete user account
    del_resp = await client.delete("/api/v1/auth/me", headers=user_headers)
    assert del_resp.status_code == 200
    assert "deleted" in del_resp.json()["message"].lower()

    # 5. Verify the token is now invalid
    me_resp = await client.get("/api/v1/auth/me", headers=user_headers)
    assert me_resp.status_code == 401

    # 6. Verify cannot log in again
    login_again = await client.post(
        "/api/v1/auth/login",
        json={"email": "delete_me@example.com", "password": "Password123!"},
    )
    assert login_again.status_code == 401




