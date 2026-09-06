import io
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_share_file_public_access(client: AsyncClient, auth_headers: dict):
    # Upload a file
    file_bytes = b"Shared confidential document"
    up_resp = await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("shared_doc.txt", io.BytesIO(file_bytes), "text/plain")},
        headers=auth_headers,
    )
    file_id = up_resp.json()["id"]

    # 1. Create a share link
    share_resp = await client.post(
        "/api/v1/shares/",
        json={
            "file_id": file_id,
            "permission": "download",
            "expires_in_hours": 24,
        },
        headers=auth_headers,
    )
    assert share_resp.status_code == 201
    share_data = share_resp.json()
    token = share_data["share_token"]
    share_id = share_data["id"]
    assert token is not None

    # 2. Access the public share WITHOUT any auth headers
    public_resp = await client.get(f"/api/v1/shares/public/{token}")
    assert public_resp.status_code == 200
    pub_data = public_resp.json()
    assert pub_data["name"] == "shared_doc.txt"
    assert pub_data["item_type"] == "file"
    assert pub_data["download_url"] is not None

    # Verify download url works anonymously
    dl_stream = await client.get(pub_data["download_url"])
    assert dl_stream.status_code == 200
    assert dl_stream.content == file_bytes

    # 3. Revoke share link
    rev_resp = await client.delete(f"/api/v1/shares/{share_id}", headers=auth_headers)
    assert rev_resp.status_code == 200

    # 4. Access after revoke should fail
    post_rev_resp = await client.get(f"/api/v1/shares/public/{token}")
    assert post_rev_resp.status_code == 404


@pytest.mark.asyncio
async def test_share_lifecycle_soft_delete_restore_and_permanent_delete(
    client: AsyncClient,
    auth_headers: dict,
    db_session,
):
    from app.models.share import SharedLink
    from sqlalchemy import select

    # 1. Upload a file
    file_bytes = b"Dynamic share lifecycle file content"
    up_resp = await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("project_notes.txt", io.BytesIO(file_bytes), "text/plain")},
        headers=auth_headers,
    )
    file_id = up_resp.json()["id"]

    # 2. Create a share link
    share_resp = await client.post(
        "/api/v1/shares/",
        json={"file_id": file_id, "permission": "download"},
        headers=auth_headers,
    )
    assert share_resp.status_code == 201
    token = share_resp.json()["share_token"]
    share_id = share_resp.json()["id"]

    # 3. Access public link -> 200 OK
    pub1 = await client.get(f"/api/v1/shares/public/{token}")
    assert pub1.status_code == 200

    # 4. Soft-delete file (move to trash) -> share becomes inactive
    del_resp = await client.delete(f"/api/v1/files/{file_id}", headers=auth_headers)
    assert del_resp.status_code == 200

    # Access public link when in trash -> 404 (inactive)
    pub_trash = await client.get(f"/api/v1/shares/public/{token}")
    assert pub_trash.status_code == 404

    # 5. Restore file -> share link reactivates
    restore_resp = await client.post(f"/api/v1/files/{file_id}/restore", headers=auth_headers)
    assert restore_resp.status_code == 200

    # Access public link after restore -> 200 OK (active again!)
    pub_restored = await client.get(f"/api/v1/shares/public/{token}")
    assert pub_restored.status_code == 200
    assert pub_restored.json()["name"] == "project_notes.txt"

    # 6. Permanently delete file -> share link record is deleted from DB
    perm_del_resp = await client.delete(f"/api/v1/files/{file_id}/permanent", headers=auth_headers)
    assert perm_del_resp.status_code == 200

    # Verify SharedLink record is deleted from database
    db_share = (await db_session.execute(select(SharedLink).where(SharedLink.id == share_id))).scalar_one_or_none()
    assert db_share is None

    # Access public link after permanent delete -> 404 Not Found
    pub_perm = await client.get(f"/api/v1/shares/public/{token}")
    assert pub_perm.status_code == 404


@pytest.mark.asyncio
async def test_shares_search_filter_and_sort(client: AsyncClient, auth_headers: dict):
    # 1. Create files and a folder
    f1 = (await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("report_financial.pdf", io.BytesIO(b"Financial report"), "application/pdf")},
        headers=auth_headers,
    )).json()

    f2 = (await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("marketing_deck.pdf", io.BytesIO(b"Marketing deck"), "application/pdf")},
        headers=auth_headers,
    )).json()

    folder = (await client.post("/api/v1/folders/", json={"name": "SharedAssets"}, headers=auth_headers)).json()

    # 2. Create shares with different permissions and targets
    s1 = (await client.post("/api/v1/shares/", json={"file_id": f1["id"], "permission": "view"}, headers=auth_headers)).json()
    s2 = (await client.post("/api/v1/shares/", json={"file_id": f2["id"], "permission": "download"}, headers=auth_headers)).json()
    s3 = (await client.post("/api/v1/shares/", json={"folder_id": folder["id"], "permission": "download"}, headers=auth_headers)).json()

    # Search by name
    res_search = (await client.get("/api/v1/shares/?search=financial", headers=auth_headers)).json()
    assert len(res_search) == 1
    assert res_search[0]["id"] == s1["id"]

    # Filter by item_type
    res_folders = (await client.get("/api/v1/shares/?item_type=folder", headers=auth_headers)).json()
    assert any(s["id"] == s3["id"] for s in res_folders)
    assert not any(s["id"] == s1["id"] for s in res_folders)

    res_files = (await client.get("/api/v1/shares/?item_type=file", headers=auth_headers)).json()
    assert any(s["id"] == s1["id"] for s in res_files)
    assert not any(s["id"] == s3["id"] for s in res_files)

    # Filter by permission
    res_view = (await client.get("/api/v1/shares/?permission=view", headers=auth_headers)).json()
    assert any(s["id"] == s1["id"] for s in res_view)
    assert not any(s["id"] == s2["id"] for s in res_view)

    # Sort by Name ASC
    res_sort_asc = (await client.get("/api/v1/shares/?sort_by=name&order=asc", headers=auth_headers)).json()
    names = [s["item_name"].lower() for s in res_sort_asc]
    assert names == sorted(names)


@pytest.mark.asyncio
async def test_share_exact_expires_at_datetime(client: AsyncClient, auth_headers: dict):
    # Upload a file
    f = (await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("exact_expiry_doc.txt", io.BytesIO(b"Exact expiration content"), "text/plain")},
        headers=auth_headers,
    )).json()

    # Create share with exact ISO timestamp in the future (e.g. 2027-01-15T00:00:00Z)
    target_iso = "2027-01-15T00:00:00Z"
    res = await client.post(
        "/api/v1/shares/",
        json={
            "file_id": f["id"],
            "permission": "view",
            "expires_at": target_iso,
        },
        headers=auth_headers,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["expires_at"] is not None
    assert "2027-01-15T00:00:00" in data["expires_at"]


@pytest.mark.asyncio
async def test_share_file_view_only_preview_and_creator_attribution(client: AsyncClient, auth_headers: dict):
    # Upload a code file
    code_content = b"print('Hello, CloudBox in-browser viewer!')\nx = 42\n"
    f = (await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("main.py", io.BytesIO(code_content), "text/x-python")},
        headers=auth_headers,
    )).json()

    # 1. Create a view-only share
    share_view = (await client.post(
        "/api/v1/shares/",
        json={"file_id": f["id"], "permission": "view"},
        headers=auth_headers,
    )).json()

    # 2. Access the public share
    pub_view = (await client.get(f"/api/v1/shares/public/{share_view['share_token']}")).json()
    assert pub_view["name"] == "main.py"
    assert pub_view["permission"] == "view"
    assert pub_view["download_url"] is None  # Direct download is blocked for view-only!
    assert pub_view["preview_url"] is not None  # In-browser preview URL is present!
    assert pub_view["shared_by_email"] is not None  # Creator attribution is present!

    # 3. Stream preview content anonymously
    preview_res = await client.get(pub_view["preview_url"])
    assert preview_res.status_code == 200
    assert preview_res.content == code_content

    # 4. Create a download share
    share_dl = (await client.post(
        "/api/v1/shares/",
        json={"file_id": f["id"], "permission": "download"},
        headers=auth_headers,
    )).json()

    pub_dl = (await client.get(f"/api/v1/shares/public/{share_dl['share_token']}")).json()
    assert pub_dl["permission"] == "download"
    assert pub_dl["download_url"] is not None
    assert pub_dl["preview_url"] is not None


@pytest.mark.asyncio
async def test_shared_folder_exploration_navigation_and_file_access(client: AsyncClient, auth_headers: dict):
    # 1. Create root folder and subfolder
    root_folder = (await client.post(
        "/api/v1/folders/",
        json={"name": "SharedProject"},
        headers=auth_headers,
    )).json()

    sub_folder = (await client.post(
        "/api/v1/folders/",
        json={"name": "src", "parent_id": root_folder["id"]},
        headers=auth_headers,
    )).json()

    # 2. Upload files in root folder and subfolder
    readme_file = (await client.post(
        "/api/v1/files/upload-direct",
        data={"folder_id": root_folder["id"]},
        files={"file": ("README.md", io.BytesIO(b"# Project Readme"), "text/markdown")},
        headers=auth_headers,
    )).json()

    app_file = (await client.post(
        "/api/v1/files/upload-direct",
        data={"folder_id": sub_folder["id"]},
        files={"file": ("app.py", io.BytesIO(b"print('running')"), "text/x-python")},
        headers=auth_headers,
    )).json()

    # Outside file not in shared folder
    outside_file = (await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("secret.txt", io.BytesIO(b"secret data"), "text/plain")},
        headers=auth_headers,
    )).json()

    # 3. Create view-only share on root folder
    share_view = (await client.post(
        "/api/v1/shares/",
        json={"folder_id": root_folder["id"], "permission": "view"},
        headers=auth_headers,
    )).json()
    token = share_view["share_token"]

    # 4. Access root folder contents
    res = await client.get(f"/api/v1/shares/public/{token}")
    assert res.status_code == 200
    data = res.json()
    assert data["item_type"] == "folder"
    assert data["name"] == "SharedProject"
    assert data["permission"] == "view"
    assert len(data["subfolders"]) == 1
    assert data["subfolders"][0]["name"] == "src"
    assert len(data["files"]) == 1
    assert data["files"][0]["name"] == "README.md"
    assert len(data["breadcrumbs"]) == 1
    assert data["breadcrumbs"][0]["name"] == "SharedProject"

    # 5. Navigate into subfolder
    sub_res = await client.get(f"/api/v1/shares/public/{token}?subfolder_id={sub_folder['id']}")
    assert sub_res.status_code == 200
    sub_data = sub_res.json()
    assert sub_data["name"] == "src"
    assert len(sub_data["files"]) == 1
    assert sub_data["files"][0]["name"] == "app.py"
    assert len(sub_data["breadcrumbs"]) == 2
    assert sub_data["breadcrumbs"][0]["name"] == "SharedProject"
    assert sub_data["breadcrumbs"][1]["name"] == "src"

    # 6. Access file inside shared folder (view only)
    file_res = await client.get(f"/api/v1/shares/public/{token}/file/{app_file['id']}")
    assert file_res.status_code == 200
    file_data = file_res.json()
    assert file_data["name"] == "app.py"
    assert file_data["permission"] == "view"
    assert file_data["download_url"] is None
    assert file_data["preview_url"] is not None

    # 7. Access file outside shared folder -> 403 Forbidden
    outside_res = await client.get(f"/api/v1/shares/public/{token}/file/{outside_file['id']}")
    assert outside_res.status_code == 403

    # 8. Create download share on root folder
    share_dl = (await client.post(
        "/api/v1/shares/",
        json={"folder_id": root_folder["id"], "permission": "download"},
        headers=auth_headers,
    )).json()
    dl_token = share_dl["share_token"]

    dl_file_res = await client.get(f"/api/v1/shares/public/{dl_token}/file/{app_file['id']}")
    assert dl_file_res.status_code == 200
    dl_file_data = dl_file_res.json()
    assert dl_file_data["permission"] == "download"
    assert dl_file_data["download_url"] is not None
    assert dl_file_data["preview_url"] is not None

    # 9. Download folder as ZIP (view-only share should be forbidden)
    view_zip_res = await client.get(f"/api/v1/shares/public/{token}/download-folder")
    assert view_zip_res.status_code == 403

    # 10. Download folder as ZIP (download permission should return presigned download_url)
    dl_zip_res = await client.get(f"/api/v1/shares/public/{dl_token}/download-folder")
    assert dl_zip_res.status_code == 200
    res_json = dl_zip_res.json()
    assert "download_url" in res_json
    assert res_json["filename"] == "SharedProject.zip"

    # Verify ZIP contents by downloading from the presigned URL
    import zipfile
    raw_zip_res = await client.get(res_json["download_url"])
    assert raw_zip_res.status_code == 200
    with zipfile.ZipFile(io.BytesIO(raw_zip_res.content), "r") as zf:
        namelist = zf.namelist()
        assert "README.md" in namelist
        assert "src/app.py" in namelist
        assert zf.read("README.md") == b"# Project Readme"
        assert zf.read("src/app.py") == b"print('running')"

