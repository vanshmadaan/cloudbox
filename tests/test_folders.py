import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_and_nest_folders(client: AsyncClient, auth_headers: dict):
    # 1. Create root folder "Documents"
    resp = await client.post(
        "/api/v1/folders/",
        json={"name": "Documents"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    doc_folder = resp.json()
    assert doc_folder["name"] == "Documents"
    assert doc_folder["parent_id"] is None
    assert doc_folder["path"] == "/Documents"

    # 2. Create subfolder "Work" inside "Documents"
    resp_sub = await client.post(
        "/api/v1/folders/",
        json={"name": "Work", "parent_id": doc_folder["id"]},
        headers=auth_headers,
    )
    assert resp_sub.status_code == 201
    work_folder = resp_sub.json()
    assert work_folder["name"] == "Work"
    assert work_folder["parent_id"] == doc_folder["id"]
    assert work_folder["path"] == "/Documents/Work"

    # 3. Create subfolder "Projects" inside "Work"
    resp_sub2 = await client.post(
        "/api/v1/folders/",
        json={"name": "Projects", "parent_id": work_folder["id"]},
        headers=auth_headers,
    )
    assert resp_sub2.status_code == 201
    proj_folder = resp_sub2.json()

    # 4. Check Breadcrumbs for "Projects"
    bread_resp = await client.get(
        f"/api/v1/folders/breadcrumbs?folder_id={proj_folder['id']}",
        headers=auth_headers,
    )
    assert bread_resp.status_code == 200
    crumbs = bread_resp.json()
    assert len(crumbs) == 4
    assert crumbs[0]["name"] == "Home"
    assert crumbs[1]["name"] == "Documents"
    assert crumbs[2]["name"] == "Work"
    assert crumbs[3]["name"] == "Projects"


@pytest.mark.asyncio
async def test_duplicate_folder_name_conflict(client: AsyncClient, auth_headers: dict):
    await client.post(
        "/api/v1/folders/",
        json={"name": "Photos"},
        headers=auth_headers,
    )
    # Attempt duplicate at root
    dup_resp = await client.post(
        "/api/v1/folders/",
        json={"name": "Photos"},
        headers=auth_headers,
    )
    assert dup_resp.status_code == 409
    assert dup_resp.json()["error"]["code"] == "FOLDER_ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_folder_tree(client: AsyncClient, auth_headers: dict):
    # Setup hierarchy
    f1 = (await client.post("/api/v1/folders/", json={"name": "Root1"}, headers=auth_headers)).json()
    f2 = (await client.post("/api/v1/folders/", json={"name": "Root2"}, headers=auth_headers)).json()
    await client.post("/api/v1/folders/", json={"name": "Child1", "parent_id": f1["id"]}, headers=auth_headers)

    tree_resp = await client.get("/api/v1/folders/tree", headers=auth_headers)
    assert tree_resp.status_code == 200
    tree = tree_resp.json()
    assert len(tree) == 2
    root1_node = next(n for n in tree if n["name"] == "Root1")
    assert len(root1_node["children"]) == 1
    assert root1_node["children"][0]["name"] == "Child1"


@pytest.mark.asyncio
async def test_prevent_circular_folder_nesting(client: AsyncClient, auth_headers: dict):
    parent = (await client.post("/api/v1/folders/", json={"name": "Parent"}, headers=auth_headers)).json()
    child = (await client.post("/api/v1/folders/", json={"name": "Child", "parent_id": parent["id"]}, headers=auth_headers)).json()

    # Attempt to move parent inside child (invalid loop)
    patch_resp = await client.patch(
        f"/api/v1/folders/{parent['id']}",
        json={"parent_id": child["id"]},
        headers=auth_headers,
    )
    assert patch_resp.status_code == 422


@pytest.mark.asyncio
async def test_folder_soft_delete_and_ancestor_inaccessibility(
    client: AsyncClient,
    auth_headers: dict,
    db_session,
):
    import io
    from app.models.share import SharedLink
    from sqlalchemy import select

    # 1. Create parent folder and nested child folder
    parent = (await client.post("/api/v1/folders/", json={"name": "Projects"}, headers=auth_headers)).json()
    child = (await client.post("/api/v1/folders/", json={"name": "Backend", "parent_id": parent["id"]}, headers=auth_headers)).json()

    # 2. Upload file in nested child folder
    file_bytes = b"Backend architecture document"
    up_resp = await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("backend_doc.txt", io.BytesIO(file_bytes), "text/plain")},
        data={"folder_id": child["id"]},
        headers=auth_headers,
    )
    assert up_resp.status_code == 201
    file_id = up_resp.json()["id"]

    # 3. Create a public share on the parent folder AND on the nested file
    folder_share_resp = await client.post(
        "/api/v1/shares/",
        json={"folder_id": parent["id"], "permission": "view"},
        headers=auth_headers,
    )
    folder_share_token = folder_share_resp.json()["share_token"]

    file_share_resp = await client.post(
        "/api/v1/shares/",
        json={"file_id": file_id, "permission": "download"},
        headers=auth_headers,
    )
    file_share_token = file_share_resp.json()["share_token"]

    # Verify public access works for both
    assert (await client.get(f"/api/v1/shares/public/{folder_share_token}")).status_code == 200
    assert (await client.get(f"/api/v1/shares/public/{file_share_token}")).status_code == 200

    # 4. Soft-delete parent folder "Projects"
    del_resp = await client.delete(f"/api/v1/folders/{parent['id']}", headers=auth_headers)
    assert del_resp.status_code == 200
    assert "moved to trash" in del_resp.json()["message"]

    # 5. Verify parent, child, file, and shares are inaccessible via public/auth endpoints
    assert (await client.get(f"/api/v1/folders/{parent['id']}", headers=auth_headers)).status_code == 404
    assert (await client.get(f"/api/v1/folders/{child['id']}", headers=auth_headers)).status_code == 404
    assert (await client.get(f"/api/v1/files/{file_id}", headers=auth_headers)).status_code == 404
    assert (await client.get(f"/api/v1/shares/public/{folder_share_token}")).status_code == 404
    assert (await client.get(f"/api/v1/shares/public/{file_share_token}")).status_code == 404

    # CRITICAL: Verify folder's own direct share link has is_active = False
    db_folder_share = (await db_session.execute(select(SharedLink).where(SharedLink.share_token == folder_share_token))).scalar_one()
    assert db_folder_share.is_active is False

    # CRITICAL: Verify file's share link record in DB was NOT mutated (is_active is still True)
    db_file_share = (await db_session.execute(select(SharedLink).where(SharedLink.share_token == file_share_token))).scalar_one()
    assert db_file_share.is_active is True

    # 6. Verify Trash listing shows Projects folder
    trash_resp = await client.get("/api/v1/folders/trash", headers=auth_headers)
    assert trash_resp.status_code == 200
    trash_folders = trash_resp.json()
    assert any(f["id"] == parent["id"] for f in trash_folders)
    # Child folder was not independently deleted, so it does not clutter trash root
    assert not any(f["id"] == child["id"] for f in trash_folders)

    # Quota is refunded
    quota = (await client.get("/api/v1/auth/quota", headers=auth_headers)).json()
    assert quota["storage_used_bytes"] == 0

    # 7. Restore parent folder "Projects"
    restore_resp = await client.post(f"/api/v1/folders/{parent['id']}/restore", headers=auth_headers)
    assert restore_resp.status_code == 200
    assert restore_resp.json()["id"] == parent["id"]

    # 8. Verify everything is accessible again
    assert (await client.get(f"/api/v1/folders/{parent['id']}", headers=auth_headers)).status_code == 200
    assert (await client.get(f"/api/v1/folders/{child['id']}", headers=auth_headers)).status_code == 200
    assert (await client.get(f"/api/v1/files/{file_id}", headers=auth_headers)).status_code == 200
    assert (await client.get(f"/api/v1/shares/public/{folder_share_token}")).status_code == 200
    assert (await client.get(f"/api/v1/shares/public/{file_share_token}")).status_code == 200

    # Verify folder share link was reactivated in DB
    await db_session.refresh(db_folder_share)
    assert db_folder_share.is_active is True

    # Quota restored
    quota_after = (await client.get("/api/v1/auth/quota", headers=auth_headers)).json()
    assert quota_after["storage_used_bytes"] == len(file_bytes)


@pytest.mark.asyncio
async def test_child_deleted_before_parent_edge_case(client: AsyncClient, auth_headers: dict):
    import io

    # 1. Create folder "Documents"
    docs = (await client.post("/api/v1/folders/", json={"name": "Documents"}, headers=auth_headers)).json()

    # 2. Upload "notes.txt" and "report.txt" into Documents
    up1 = await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("notes.txt", io.BytesIO(b"Secret notes"), "text/plain")},
        data={"folder_id": docs["id"]},
        headers=auth_headers,
    )
    notes_id = up1.json()["id"]

    up2 = await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("report.txt", io.BytesIO(b"Quarterly report"), "text/plain")},
        data={"folder_id": docs["id"]},
        headers=auth_headers,
    )
    report_id = up2.json()["id"]

    # 3. Step 1: User soft-deletes "notes.txt" first (Day 1)
    del_notes = await client.delete(f"/api/v1/files/{notes_id}", headers=auth_headers)
    assert del_notes.status_code == 200

    # 4. Step 2: User soft-deletes root folder "Documents" (Day 5)
    del_docs = await client.delete(f"/api/v1/folders/{docs['id']}", headers=auth_headers)
    assert del_docs.status_code == 200

    # 5. Check Trash
    trash_files = (await client.get("/api/v1/files/trash", headers=auth_headers)).json()
    assert any(f["id"] == notes_id for f in trash_files)
    # report.txt was not independently deleted, so it's not in standalone trash
    assert not any(f["id"] == report_id for f in trash_files)

    trash_folders = (await client.get("/api/v1/folders/trash", headers=auth_headers)).json()
    assert any(f["id"] == docs["id"] for f in trash_folders)

    # 6. Step 3: User restores root folder "Documents"
    res_docs = await client.post(f"/api/v1/folders/{docs['id']}/restore", headers=auth_headers)
    assert res_docs.status_code == 200

    # 7. CRITICAL VERIFICATION:
    # "Documents" is restored and "report.txt" is active inside it
    assert (await client.get(f"/api/v1/folders/{docs['id']}", headers=auth_headers)).status_code == 200
    assert (await client.get(f"/api/v1/files/{report_id}", headers=auth_headers)).status_code == 200

    # "notes.txt" MUST REMAIN IN TRASH!
    assert (await client.get(f"/api/v1/files/{notes_id}", headers=auth_headers)).status_code == 404
    trash_files_after = (await client.get("/api/v1/files/trash", headers=auth_headers)).json()
    assert any(f["id"] == notes_id for f in trash_files_after)

    # 8. User can now restore "notes.txt" independently
    res_notes = await client.post(f"/api/v1/files/{notes_id}/restore", headers=auth_headers)
    assert res_notes.status_code == 200
    assert (await client.get(f"/api/v1/files/{notes_id}", headers=auth_headers)).status_code == 200


@pytest.mark.asyncio
async def test_restore_child_when_parent_in_trash(client: AsyncClient, auth_headers: dict):
    import io

    # Create folder and file
    folder = (await client.post("/api/v1/folders/", json={"name": "TempFolder"}, headers=auth_headers)).json()
    up = await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("orphan_doc.txt", io.BytesIO(b"Orphan doc"), "text/plain")},
        data={"folder_id": folder["id"]},
        headers=auth_headers,
    )
    file_id = up.json()["id"]

    # Delete file, then delete parent folder
    await client.delete(f"/api/v1/files/{file_id}", headers=auth_headers)
    await client.delete(f"/api/v1/folders/{folder['id']}", headers=auth_headers)

    # Restore file while parent is still in trash
    res = await client.post(f"/api/v1/files/{file_id}/restore", headers=auth_headers)
    assert res.status_code == 200
    restored_file = res.json()
    # File is re-parented to root because parent is in trash
    assert restored_file["folder_id"] is None

    # File is accessible at root
    assert (await client.get(f"/api/v1/files/{file_id}", headers=auth_headers)).status_code == 200


@pytest.mark.asyncio
async def test_permanent_delete_folder_cleans_all_descendants(
    client: AsyncClient,
    auth_headers: dict,
    db_session,
):
    import io
    from app.models.blob import ContentBlob
    from sqlalchemy import select

    # Create nested structure with files (one active, one soft-deleted)
    root_f = (await client.post("/api/v1/folders/", json={"name": "ToPurge"}, headers=auth_headers)).json()
    child_f = (await client.post("/api/v1/folders/", json={"name": "SubPurge", "parent_id": root_f["id"]}, headers=auth_headers)).json()

    unique_bytes = b"Unique permanent deletion folder content 999"
    up = await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("purge_file.txt", io.BytesIO(unique_bytes), "text/plain")},
        data={"folder_id": child_f["id"]},
        headers=auth_headers,
    )
    file_id = up.json()["id"]

    # Soft-delete file into trash
    await client.delete(f"/api/v1/files/{file_id}", headers=auth_headers)

    # Verify blob exists
    import hashlib
    sha256 = hashlib.sha256(unique_bytes).hexdigest()
    blob = (await db_session.execute(select(ContentBlob).where(ContentBlob.checksum_sha256 == sha256))).scalar_one_or_none()
    assert blob is not None

    # Permanently delete root folder
    perm_del = await client.delete(f"/api/v1/folders/{root_f['id']}/permanent", headers=auth_headers)
    assert perm_del.status_code == 200

    # Verify root, child, and file are permanently gone
    assert (await client.get(f"/api/v1/folders/{root_f['id']}", headers=auth_headers)).status_code == 404
    assert (await client.get(f"/api/v1/folders/{child_f['id']}", headers=auth_headers)).status_code == 404
    assert (await client.get(f"/api/v1/files/{file_id}", headers=auth_headers)).status_code == 404

    # Verify ContentBlob DB row was purged
    blob_after = (await db_session.execute(select(ContentBlob).where(ContentBlob.checksum_sha256 == sha256))).scalar_one_or_none()
    assert blob_after is None


@pytest.mark.asyncio
async def test_14_day_retention_purge_folders(
    client: AsyncClient,
    auth_headers: dict,
    db_session,
):
    from datetime import datetime, timedelta, timezone
    from app.models.folder import Folder
    from sqlalchemy import select

    # Create folder and soft-delete it
    folder = (await client.post("/api/v1/folders/", json={"name": "OldFolder"}, headers=auth_headers)).json()
    await client.delete(f"/api/v1/folders/{folder['id']}", headers=auth_headers)

    # Artificially age the deleted_at date in DB to 15 days ago
    folder_obj = (await db_session.execute(select(Folder).where(Folder.id == folder["id"]))).scalar_one()
    folder_obj.deleted_at = datetime.now(timezone.utc) - timedelta(days=15)
    await db_session.commit()

    # Trigger retention purge
    purge_resp = await client.post("/api/v1/folders/purge-expired?retention_days=14", headers=auth_headers)
    assert purge_resp.status_code == 200
    assert "Purged 1 expired folders" in purge_resp.json()["message"]

    # Verify completely purged from DB
    db_folder = (await db_session.execute(select(Folder).where(Folder.id == folder["id"]))).scalar_one_or_none()
    assert db_folder is None


@pytest.mark.asyncio
async def test_trash_folder_contents(client: AsyncClient, auth_headers: dict):
    import io

    # 1. Create parent folder "Project"
    parent = (await client.post("/api/v1/folders/", json={"name": "Project"}, headers=auth_headers)).json()
    p_id = parent["id"]

    # 2. Create subfolders "Docs" and "Assets" inside Project
    sub1 = (await client.post("/api/v1/folders/", json={"name": "Docs", "parent_id": p_id}, headers=auth_headers)).json()
    sub2 = (await client.post("/api/v1/folders/", json={"name": "Assets", "parent_id": p_id}, headers=auth_headers)).json()

    # 3. Create files inside Project
    f1 = (await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("readme.md", io.BytesIO(b"# Readme"), "text/plain")},
        data={"folder_id": p_id},
        headers=auth_headers,
    )).json()

    # 4. Trigger trash-contents on Project
    trash_res = await client.post(f"/api/v1/folders/trash-contents?folder_id={p_id}", headers=auth_headers)
    assert trash_res.status_code == 200
    assert "Moved 2 folders and 1 files to trash" in trash_res.json()["message"]

    # 5. Verify parent folder Project is still active
    p_check = await client.get(f"/api/v1/folders/{p_id}", headers=auth_headers)
    assert p_check.status_code == 200

    # 6. Verify subfolders and files inside Project are now in trash (and inaccessible directly)
    assert (await client.get(f"/api/v1/folders/{sub1['id']}", headers=auth_headers)).status_code == 404
    assert (await client.get(f"/api/v1/folders/{sub2['id']}", headers=auth_headers)).status_code == 404
    assert (await client.get(f"/api/v1/files/{f1['id']}", headers=auth_headers)).status_code == 404

    # 7. Check Trash list
    trash_f = (await client.get("/api/v1/folders/trash", headers=auth_headers)).json()
    trash_files = (await client.get("/api/v1/files/trash", headers=auth_headers)).json()
    assert any(f["id"] == sub1["id"] for f in trash_f)
    assert any(f["id"] == sub2["id"] for f in trash_f)
    assert any(f["id"] == f1["id"] for f in trash_files)


@pytest.mark.asyncio
async def test_user_reported_flow(client: AsyncClient, auth_headers: dict):
    import io

    # 1. Create subfolder
    sub = (await client.post("/api/v1/folders/", json={"name": "subfolder"}, headers=auth_headers)).json()

    # 2. Upload 2 files in subfolder
    f1 = (await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("file1.txt", io.BytesIO(b"Hello world 1"), "text/plain")},
        data={"folder_id": sub["id"]},
        headers=auth_headers,
    )).json()

    f2 = (await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("file2.txt", io.BytesIO(b"Hello world 2 longer text"), "text/plain")},
        data={"folder_id": sub["id"]},
        headers=auth_headers,
    )).json()

    # 3. Upload 1 video in root
    f_vid = (await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("video.mp4", io.BytesIO(b"Fake video binary data bytes"), "video/mp4")},
        headers=auth_headers,
    )).json()

    quota_before = (await client.get("/api/v1/auth/quota", headers=auth_headers)).json()
    expected_size = f1["file_size"] + f2["file_size"] + f_vid["file_size"]
    assert quota_before["storage_used_bytes"] == expected_size

    # 4. Move all root contents to trash
    t_res = await client.post("/api/v1/folders/trash-contents", headers=auth_headers)
    assert t_res.status_code == 200

    quota_after_trash = (await client.get("/api/v1/auth/quota", headers=auth_headers)).json()
    assert quota_after_trash["storage_used_bytes"] == 0

    # 5. Empty trash bin
    empty_res = await client.delete("/api/v1/files/trash/empty", headers=auth_headers)
    assert empty_res.status_code == 200

    # 6. Check quota after empty trash
    quota_after_empty = (await client.get("/api/v1/auth/quota", headers=auth_headers)).json()
    assert quota_after_empty["storage_used_bytes"] == 0


@pytest.mark.asyncio
async def test_user_reported_alternative_flow(client: AsyncClient, auth_headers: dict):
    import io

    # 1. Create subfolder
    sub = (await client.post("/api/v1/folders/", json={"name": "subfolder"}, headers=auth_headers)).json()

    # 2. Upload 2 files in subfolder (1.54 KB total)
    f1 = (await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("file1.txt", io.BytesIO(b"a" * 1000), "text/plain")},
        data={"folder_id": sub["id"]},
        headers=auth_headers,
    )).json()

    f2 = (await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("file2.txt", io.BytesIO(b"b" * 576), "text/plain")},
        data={"folder_id": sub["id"]},
        headers=auth_headers,
    )).json()

    # 3. Upload 1 video in root
    f_vid = (await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("video.mp4", io.BytesIO(b"Fake video binary data bytes"), "video/mp4")},
        headers=auth_headers,
    )).json()

    # 4. User moves contents of subfolder to trash FIRST
    t_sub = await client.post(f"/api/v1/folders/trash-contents?folder_id={sub['id']}", headers=auth_headers)
    assert t_sub.status_code == 200

    # 5. User moves root contents to trash
    t_root = await client.post("/api/v1/folders/trash-contents", headers=auth_headers)
    assert t_root.status_code == 200

    # 6. User deletes folder permanently from trash
    p_folder = await client.delete(f"/api/v1/folders/{sub['id']}/permanent", headers=auth_headers)
    assert p_folder.status_code == 200

    # 7. User deletes video permanently from trash
    p_vid = await client.delete(f"/api/v1/files/{f_vid['id']}/permanent", headers=auth_headers)
    assert p_vid.status_code == 200

    # Check quota
    quota = (await client.get("/api/v1/auth/quota", headers=auth_headers)).json()
    assert quota["storage_used_bytes"] == 0


@pytest.mark.asyncio
async def test_folders_search_and_sort(client: AsyncClient, auth_headers: dict):
    # 1. Create folders with distinct names
    await client.post("/api/v1/folders/", json={"name": "ZebraDocs"}, headers=auth_headers)
    await client.post("/api/v1/folders/", json={"name": "AlphaDocs"}, headers=auth_headers)
    await client.post("/api/v1/folders/", json={"name": "BetaPhotos"}, headers=auth_headers)

    # Search filter
    search_res = (await client.get("/api/v1/folders/?search=Docs", headers=auth_headers)).json()
    names = [f["name"] for f in search_res]
    assert "ZebraDocs" in names
    assert "AlphaDocs" in names
    assert "BetaPhotos" not in names

    # Sort ASC
    sort_asc = (await client.get("/api/v1/folders/?sort_by=name&order=asc", headers=auth_headers)).json()
    names_asc = [f["name"] for f in sort_asc]
    assert names_asc == sorted(names_asc)

    # Sort DESC
    sort_desc = (await client.get("/api/v1/folders/?sort_by=name&order=desc", headers=auth_headers)).json()
    names_desc = [f["name"] for f in sort_desc]
    assert names_desc == sorted(names_desc, reverse=True)


@pytest.mark.asyncio
async def test_trash_folders_search_and_sort(client: AsyncClient, auth_headers: dict):
    f1 = (await client.post("/api/v1/folders/", json={"name": "TrashZebra"}, headers=auth_headers)).json()
    f2 = (await client.post("/api/v1/folders/", json={"name": "TrashAlpha"}, headers=auth_headers)).json()

    await client.delete(f"/api/v1/folders/{f1['id']}", headers=auth_headers)
    await client.delete(f"/api/v1/folders/{f2['id']}", headers=auth_headers)

    # Search in trash folders
    trash_search = (await client.get("/api/v1/folders/trash?search=Zebra", headers=auth_headers)).json()
    assert len(trash_search) == 1
    assert trash_search[0]["name"] == "TrashZebra"

    # Sort trash folders
    trash_sort = (await client.get("/api/v1/folders/trash?sort_by=name&order=asc", headers=auth_headers)).json()
    t_names = [f["name"] for f in trash_sort]
    assert t_names == sorted(t_names)


@pytest.mark.asyncio
async def test_rename_folder_success_and_validation(client: AsyncClient, auth_headers: dict):
    # 1. Create two root folders
    f1 = (await client.post("/api/v1/folders/", json={"name": "FolderOne"}, headers=auth_headers)).json()
    f2 = (await client.post("/api/v1/folders/", json={"name": "FolderTwo"}, headers=auth_headers)).json()

    # 2. Successfully rename FolderOne -> FolderRenamed
    patch_resp = await client.patch(
        f"/api/v1/folders/{f1['id']}",
        json={"name": "FolderRenamed"},
        headers=auth_headers,
    )
    assert patch_resp.status_code == 200
    updated = patch_resp.json()
    assert updated["name"] == "FolderRenamed"
    assert updated["path"] == "/FolderRenamed"

    # 3. Rename with empty or whitespace name -> 422
    empty_resp = await client.patch(
        f"/api/v1/folders/{f1['id']}",
        json={"name": "   "},
        headers=auth_headers,
    )
    assert empty_resp.status_code == 422

    # 4. Rename to existing sibling name -> 422 (duplicate error)
    dup_resp = await client.patch(
        f"/api/v1/folders/{f1['id']}",
        json={"name": "FolderTwo"},
        headers=auth_headers,
    )
    assert dup_resp.status_code == 422
    assert "already exists" in dup_resp.json()["error"]["message"]


@pytest.mark.asyncio
async def test_move_folder_success_and_validation(client: AsyncClient, auth_headers: dict):
    # Setup hierarchy: RootA, RootB, and RootA/SubA
    root_a = (await client.post("/api/v1/folders/", json={"name": "RootA"}, headers=auth_headers)).json()
    root_b = (await client.post("/api/v1/folders/", json={"name": "RootB"}, headers=auth_headers)).json()
    sub_a = (await client.post("/api/v1/folders/", json={"name": "SubA", "parent_id": root_a["id"]}, headers=auth_headers)).json()
    sub_sub = (await client.post("/api/v1/folders/", json={"name": "DeepChild", "parent_id": sub_a["id"]}, headers=auth_headers)).json()

    # 1. Move RootA into RootB
    move_resp = await client.patch(
        f"/api/v1/folders/{root_a['id']}",
        json={"parent_id": root_b["id"]},
        headers=auth_headers,
    )
    assert move_resp.status_code == 200
    moved_a = move_resp.json()
    assert moved_a["parent_id"] == root_b["id"]
    assert moved_a["path"] == "/RootB/RootA"

    # Verify descendant paths were updated recursively
    deep_check = (await client.get(f"/api/v1/folders/{sub_sub['id']}", headers=auth_headers)).json()
    assert deep_check["path"] == "/RootB/RootA/SubA/DeepChild"

    # 2. Move RootA back to root (parent_id: null)
    root_move_resp = await client.patch(
        f"/api/v1/folders/{root_a['id']}",
        json={"parent_id": None},
        headers=auth_headers,
    )
    assert root_move_resp.status_code == 200
    restored_a = root_move_resp.json()
    assert restored_a["parent_id"] is None
    assert restored_a["path"] == "/RootA"

    deep_check_restored = (await client.get(f"/api/v1/folders/{sub_sub['id']}", headers=auth_headers)).json()
    assert deep_check_restored["path"] == "/RootA/SubA/DeepChild"

    # 3. Circular move check: move RootA into its own descendant SubA -> 422
    circ_resp = await client.patch(
        f"/api/v1/folders/{root_a['id']}",
        json={"parent_id": sub_a["id"]},
        headers=auth_headers,
    )
    assert circ_resp.status_code == 422

    # 4. Circular move check: move RootA into itself -> 422
    self_resp = await client.patch(
        f"/api/v1/folders/{root_a['id']}",
        json={"parent_id": root_a["id"]},
        headers=auth_headers,
    )
    assert self_resp.status_code == 422


@pytest.mark.asyncio
async def test_recreate_folder_after_soft_delete(client: AsyncClient, auth_headers: dict):
    # Create parent folder
    parent = (await client.post("/api/v1/folders/", json={"name": "ParentDir"}, headers=auth_headers)).json()
    
    # Create child folder
    child = (await client.post("/api/v1/folders/", json={"name": "ChildDir", "parent_id": parent["id"]}, headers=auth_headers)).json()
    
    # Soft delete child folder
    del_res = await client.delete(f"/api/v1/folders/{child['id']}", headers=auth_headers)
    assert del_res.status_code == 200
    
    # Recreate child folder with same name in same parent
    recreate_res = await client.post("/api/v1/folders/", json={"name": "ChildDir", "parent_id": parent["id"]}, headers=auth_headers)
    assert recreate_res.status_code == 201


@pytest.mark.asyncio
async def test_restore_folder_conflict_with_active_folder(client: AsyncClient, auth_headers: dict):
    # 1. Create root folder "ConfFolder"
    f1 = (await client.post("/api/v1/folders/", json={"name": "ConfFolder"}, headers=auth_headers)).json()
    # 2. Delete it (to trash)
    await client.delete(f"/api/v1/folders/{f1['id']}", headers=auth_headers)
    # 3. Create another folder with same name "ConfFolder" (active)
    f2 = (await client.post("/api/v1/folders/", json={"name": "ConfFolder"}, headers=auth_headers)).json()
    assert f2["id"] != f1["id"]
    # 4. Attempt to restore f1 from trash -> Should raise 409 Conflict
    res = await client.post(f"/api/v1/folders/{f1['id']}/restore", headers=auth_headers)
    print("RESTORE STATUS:", res.status_code, res.text)
    assert res.status_code == 409




