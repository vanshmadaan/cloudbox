import io
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_full_app_end_to_end_flow(client: AsyncClient):
    # 1. Test Static Asset Serving
    root_resp = await client.get("/")
    assert root_resp.status_code == 200
    assert "CloudBox" in root_resp.text
    assert "modal-confirm" in root_resp.text
    assert "share-expiry-preset" in root_resp.text

    css_resp = await client.get("/static/style.css")
    assert css_resp.status_code == 200

    js_resp = await client.get("/static/app.js")
    assert js_resp.status_code == 200
    assert "showConfirmModal" in js_resp.text

    # 2. Test User Signup and Login
    email = "e2e_user@example.com"
    pwd = "StrongPassword123!"
    signup_resp = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": pwd, "full_name": "E2E Test User"},
    )
    assert signup_resp.status_code == 201

    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": pwd},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 3. Test Profile and Quota
    profile_resp = await client.get("/api/v1/auth/me", headers=headers)
    assert profile_resp.status_code == 200
    assert profile_resp.json()["email"] == email

    quota_resp = await client.get("/api/v1/auth/quota", headers=headers)
    assert quota_resp.status_code == 200
    assert quota_resp.json()["storage_used_bytes"] == 0

    # 4. Create Nested Folders
    f1_resp = await client.post("/api/v1/folders/", json={"name": "Projects"}, headers=headers)
    assert f1_resp.status_code == 201
    f1_id = f1_resp.json()["id"]

    f2_resp = await client.post("/api/v1/folders/", json={"name": "SubProject", "parent_id": f1_id}, headers=headers)
    assert f2_resp.status_code == 201
    f2_id = f2_resp.json()["id"]

    # 5. Direct Upload File into Subfolder
    file_bytes = b"Hello Cloud Storage Full App E2E Test Content"
    up_resp = await client.post(
        "/api/v1/files/upload-direct",
        data={"folder_id": f2_id},
        files={"file": ("project_spec.pdf", io.BytesIO(file_bytes), "application/pdf")},
        headers=headers,
    )
    assert up_resp.status_code == 201
    file_id = up_resp.json()["id"]

    # Verify quota updated
    quota_resp = await client.get("/api/v1/auth/quota", headers=headers)
    assert quota_resp.json()["storage_used_bytes"] == len(file_bytes)

    # 6. List and Filter Files & Folders
    files_resp = await client.get(f"/api/v1/files/?folder_id={f2_id}&file_type=document", headers=headers)
    assert files_resp.status_code == 200
    assert len(files_resp.json()) == 1
    assert files_resp.json()[0]["name"] == "project_spec.pdf"

    # 7. Create Share Link with Exact Timestamp
    share_resp = await client.post(
        "/api/v1/shares/",
        json={
            "file_id": file_id,
            "permission": "download",
            "expires_at": "2028-01-01T00:00:00Z",
        },
        headers=headers,
    )
    assert share_resp.status_code == 201
    share_token = share_resp.json()["share_token"]
    share_id = share_resp.json()["id"]

    # Anonymous Access of Shared Link
    public_resp = await client.get(f"/api/v1/shares/public/{share_token}")
    assert public_resp.status_code == 200
    assert public_resp.json()["name"] == "project_spec.pdf"
    assert public_resp.json()["download_url"] is not None

    # Download anonymous file
    dl_resp = await client.get(public_resp.json()["download_url"])
    assert dl_resp.status_code == 200
    assert dl_resp.content == file_bytes

    # 8. Trash and Restore Flow
    # Directly delete file to trash
    del_file_resp = await client.delete(f"/api/v1/files/{file_id}", headers=headers)
    assert del_file_resp.status_code == 200

    # Verify file is in trash
    trash_files_resp = await client.get("/api/v1/files/trash", headers=headers)
    assert any(f["id"] == file_id for f in trash_files_resp.json())

    # Trash parent folder contents (subfolder f2_id)
    trash_contents_resp = await client.post(f"/api/v1/folders/trash-contents?folder_id={f1_id}", headers=headers)
    assert trash_contents_resp.status_code == 200

    # Verify subfolder is in trash
    trash_folders_resp = await client.get("/api/v1/folders/trash", headers=headers)
    assert any(f["id"] == f2_id for f in trash_folders_resp.json())

    # Restore all trash
    restore_all_resp = await client.post("/api/v1/files/trash/restore-all", headers=headers)
    assert restore_all_resp.status_code == 200

    # Verify file and subfolder are active again
    active_folders = await client.get(f"/api/v1/folders/?parent_id={f1_id}", headers=headers)
    assert any(f["id"] == f2_id for f in active_folders.json())

    active_files = await client.get(f"/api/v1/files/?folder_id={f2_id}", headers=headers)
    assert any(f["id"] == file_id for f in active_files.json())

    # 9. Clean up share
    del_share_resp = await client.delete(f"/api/v1/shares/{share_id}", headers=headers)
    assert del_share_resp.status_code == 200
