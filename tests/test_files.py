import hashlib
import io
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_presigned_upload_and_complete_flow(client: AsyncClient, auth_headers: dict):
    file_bytes = b"Hello Cloud Storage Serverless Architecture!"
    file_size = len(file_bytes)
    sha256 = hashlib.sha256(file_bytes).hexdigest()

    # Step 1: Request presigned upload URL
    req_resp = await client.post(
        "/api/v1/files/upload-url",
        json={
            "name": "architecture.txt",
            "file_size": file_size,
            "content_type": "text/plain",
        },
        headers=auth_headers,
    )
    assert req_resp.status_code == 200
    presigned = req_resp.json()
    assert "upload_url" in presigned
    assert "temp_s3_key" in presigned

    # Step 2: Upload bytes directly to local storage / S3 simulation endpoint
    put_resp = await client.put(
        presigned["upload_url"],
        content=file_bytes,
        headers={"Content-Type": "text/plain"},
    )
    assert put_resp.status_code == 200

    # Step 3: Complete upload
    comp_resp = await client.post(
        "/api/v1/files/complete-upload",
        json={
            "temp_s3_key": presigned["temp_s3_key"],
            "name": "architecture.txt",
            "file_size": file_size,
            "checksum_sha256": sha256,
            "content_type": "text/plain",
        },
        headers=auth_headers,
    )
    assert comp_resp.status_code == 201
    file_data = comp_resp.json()
    assert file_data["name"] == "architecture.txt"
    assert file_data["file_size"] == file_size

    # Step 4: Verify Download URL works
    dl_resp = await client.get(
        f"/api/v1/files/{file_data['id']}/download",
        headers=auth_headers,
    )
    assert dl_resp.status_code == 200
    dl_info = dl_resp.json()
    assert "download_url" in dl_info

    # Fetch actual stream
    stream_resp = await client.get(dl_info["download_url"])
    assert stream_resp.status_code == 200
    assert stream_resp.content == file_bytes


@pytest.mark.asyncio
async def test_direct_multipart_upload(client: AsyncClient, auth_headers: dict):
    file_content = b"Direct multipart file content"
    files = {
        "file": ("multipart_sample.txt", io.BytesIO(file_content), "text/plain")
    }

    resp = await client.post(
        "/api/v1/files/upload-direct",
        files=files,
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "multipart_sample.txt"
    assert data["file_size"] == len(file_content)


@pytest.mark.asyncio
async def test_content_deduplication(client: AsyncClient, auth_headers: dict):
    shared_content = b"Exact same binary content for deduplication test!"

    # Upload File 1
    f1 = await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("original.txt", io.BytesIO(shared_content), "text/plain")},
        headers=auth_headers,
    )
    assert f1.status_code == 201

    # Upload File 2 with identical content but different name
    f2 = await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("duplicate_copy.txt", io.BytesIO(shared_content), "text/plain")},
        headers=auth_headers,
    )
    assert f2.status_code == 201

    # Both files exist independently in the user's directory
    list_resp = await client.get("/api/v1/files/", headers=auth_headers)
    files = list_resp.json()
    names = [f["name"] for f in files]
    assert "original.txt" in names
    assert "duplicate_copy.txt" in names


@pytest.mark.asyncio
async def test_duplicate_filename_auto_renaming(
    client: AsyncClient,
    auth_headers: dict,
    db_session,
):
    from app.models.blob import ContentBlob
    from sqlalchemy import select
    import hashlib

    same_content = b"Constant content uploaded 3 times"
    sha256 = hashlib.sha256(same_content).hexdigest()

    # Upload the exact same file 3 times without file_id
    r1 = await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("notes.txt", io.BytesIO(same_content), "text/plain")},
        headers=auth_headers,
    )
    assert r1.status_code == 201
    assert r1.json()["name"] == "notes.txt"

    r2 = await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("notes.txt", io.BytesIO(same_content), "text/plain")},
        headers=auth_headers,
    )
    assert r2.status_code == 201
    assert r2.json()["name"] == "notes (1).txt"

    r3 = await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("notes.txt", io.BytesIO(same_content), "text/plain")},
        headers=auth_headers,
    )
    assert r3.status_code == 201
    assert r3.json()["name"] == "notes (2).txt"

    # Verify that ref_count is 3 (3 file entities referencing the single deduplicated blob)
    blob_res = await db_session.execute(
        select(ContentBlob).where(ContentBlob.checksum_sha256 == sha256)
    )
    blob = blob_res.scalar_one_or_none()
    assert blob is not None
    assert blob.ref_count == 3


@pytest.mark.asyncio
async def test_file_overwrite_content(client: AsyncClient, auth_headers: dict):
    content1 = b"Content of Initial Document"
    content2 = b"Content of Overwritten Document - Brand New Data"

    # 1. Upload initial file
    resp1 = await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("report.txt", io.BytesIO(content1), "text/plain")},
        headers=auth_headers,
    )
    assert resp1.status_code == 201
    f1 = resp1.json()
    assert f1["file_size"] == len(content1)

    # 2. Upload second file with explicit file_id to overwrite
    resp2 = await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("report.txt", io.BytesIO(content2), "text/plain")},
        data={"file_id": f1["id"]},
        headers=auth_headers,
    )
    assert resp2.status_code == 201
    f2 = resp2.json()
    assert f2["id"] == f1["id"]  # Overwrote existing file
    assert f2["file_size"] == len(content2)

    # 3. Verify downloading retrieves the updated content
    dl_resp = await client.get(f"/api/v1/files/{f1['id']}/download", headers=auth_headers)
    assert dl_resp.status_code == 200
    stream = await client.get(dl_resp.json()["download_url"])
    assert stream.content == content2

    # 4. Verify user quota matches the new file size
    quota_resp = await client.get("/api/v1/auth/quota", headers=auth_headers)
    assert quota_resp.json()["storage_used_bytes"] == len(content2)


@pytest.mark.asyncio
async def test_quota_exceeded_blocking(client: AsyncClient, auth_headers: dict):
    # Attempt to request upload exceeding 100MB default quota
    huge_size = 200 * 1024 * 1024  # 200MB
    resp = await client.post(
        "/api/v1/files/upload-url",
        json={
            "name": "huge_movie.mp4",
            "file_size": huge_size,
            "content_type": "video/mp4",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 413
    data = resp.json()
    assert data["error"]["code"] == "QUOTA_EXCEEDED"


@pytest.mark.asyncio
async def test_file_delete_and_quota_refund(client: AsyncClient, auth_headers: dict):
    content = b"A" * 1024 * 1024  # 1 MB
    up_resp = await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("1mb_file.bin", io.BytesIO(content), "application/octet-stream")},
        headers=auth_headers,
    )
    file_id = up_resp.json()["id"]

    # Verify quota increased
    q1 = (await client.get("/api/v1/auth/quota", headers=auth_headers)).json()
    assert q1["storage_used_bytes"] == len(content)

    # Delete file
    del_resp = await client.delete(f"/api/v1/files/{file_id}", headers=auth_headers)
    assert del_resp.status_code == 200

    # Verify quota refunded back to 0
    q2 = (await client.get("/api/v1/auth/quota", headers=auth_headers)).json()
    assert q2["storage_used_bytes"] == 0


@pytest.mark.asyncio
async def test_file_patch_rename_and_move(client: AsyncClient, auth_headers: dict):
    # Create folder
    folder = (await client.post("/api/v1/folders/", json={"name": "Archive"}, headers=auth_headers)).json()

    # Upload file
    up_resp = await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("draft.txt", io.BytesIO(b"Draft notes"), "text/plain")},
        headers=auth_headers,
    )
    file_id = up_resp.json()["id"]

    # Rename and move file to folder
    patch_resp = await client.patch(
        f"/api/v1/files/{file_id}",
        json={"name": "final_draft.txt", "folder_id": folder["id"]},
        headers=auth_headers,
    )
    assert patch_resp.status_code == 200
    patched = patch_resp.json()
    assert patched["name"] == "final_draft.txt"
    assert patched["folder_id"] == folder["id"]


@pytest.mark.asyncio
async def test_user_data_isolation(
    client: AsyncClient,
    auth_headers: dict,
    secondary_auth_headers: dict,
):
    # User 1 uploads file
    up_resp = await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("user1_private.txt", io.BytesIO(b"Secret 1"), "text/plain")},
        headers=auth_headers,
    )
    file_id = up_resp.json()["id"]

    # User 2 cannot access User 1's file
    get_resp = await client.get(f"/api/v1/files/{file_id}", headers=secondary_auth_headers)
    assert get_resp.status_code == 404

    # User 2 cannot delete User 1's file
    del_resp = await client.delete(f"/api/v1/files/{file_id}", headers=secondary_auth_headers)
    assert del_resp.status_code == 404


@pytest.mark.asyncio
async def test_soft_delete_and_restore_flow(client: AsyncClient, auth_headers: dict):
    content = b"Soft delete test document"
    up_resp = await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("to_delete.txt", io.BytesIO(content), "text/plain")},
        headers=auth_headers,
    )
    assert up_resp.status_code == 201
    file_id = up_resp.json()["id"]

    # 1. Soft-delete the file
    del_resp = await client.delete(f"/api/v1/files/{file_id}", headers=auth_headers)
    assert del_resp.status_code == 200
    assert "retained for 14 days" in del_resp.json()["message"]

    # 2. Verify file is no longer in active list
    files_resp = await client.get("/api/v1/files/", headers=auth_headers)
    active_ids = [f["id"] for f in files_resp.json()]
    assert file_id not in active_ids

    # 3. Verify file appears in trash with retention days
    trash_resp = await client.get("/api/v1/files/trash", headers=auth_headers)
    assert trash_resp.status_code == 200
    trash_files = trash_resp.json()
    trash_ids = [f["id"] for f in trash_files]
    assert file_id in trash_ids
    deleted_item = next(f for f in trash_files if f["id"] == file_id)
    assert deleted_item["days_until_purge"] == 14

    # 4. Restore file
    restore_resp = await client.post(f"/api/v1/files/{file_id}/restore", headers=auth_headers)
    assert restore_resp.status_code == 200
    assert restore_resp.json()["is_deleted"] is False

    # 5. Verify file is back in active list and gone from trash
    files_resp_after = await client.get("/api/v1/files/", headers=auth_headers)
    assert file_id in [f["id"] for f in files_resp_after.json()]

    trash_resp_after = await client.get("/api/v1/files/trash", headers=auth_headers)
    assert file_id not in [f["id"] for f in trash_resp_after.json()]


@pytest.mark.asyncio
async def test_14_day_retention_purge_job(client: AsyncClient, auth_headers: dict, db_session: AsyncSession):
    from datetime import datetime, timedelta, timezone
    from app.models.file import File
    from sqlalchemy import select

    # Upload file
    up_resp = await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("old_doc.txt", io.BytesIO(b"Old archive bytes"), "text/plain")},
        headers=auth_headers,
    )
    file_id = up_resp.json()["id"]

    # Soft delete file
    await client.delete(f"/api/v1/files/{file_id}", headers=auth_headers)

    # Artificially age the deleted_at date in DB to 15 days ago
    file_obj = (await db_session.execute(select(File).where(File.id == file_id))).scalar_one()
    file_obj.deleted_at = datetime.now(timezone.utc) - timedelta(days=15)
    await db_session.commit()

    # Trigger retention purge with 14-day threshold
    purge_resp = await client.post("/api/v1/files/purge-expired?retention_days=14", headers=auth_headers)
    assert purge_resp.status_code == 200
    assert "Purged 1 expired files" in purge_resp.json()["message"]

    # Verify completely purged from DB
    db_file = (await db_session.execute(select(File).where(File.id == file_id))).scalar_one_or_none()
    assert db_file is None


@pytest.mark.asyncio
async def test_content_blob_pruning_on_permanent_delete(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    from app.models.blob import ContentBlob
    from sqlalchemy import select

    # Upload unique file
    unique_bytes = b"Unique content for blob deletion test 12345"
    up_resp = await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("blob_test.txt", io.BytesIO(unique_bytes), "text/plain")},
        headers=auth_headers,
    )
    assert up_resp.status_code == 201
    file_id = up_resp.json()["id"]

    # Verify ContentBlob exists with ref_count == 1
    sha256 = hashlib.sha256(unique_bytes).hexdigest()
    blob = (await db_session.execute(select(ContentBlob).where(ContentBlob.checksum_sha256 == sha256))).scalar_one_or_none()
    assert blob is not None
    assert blob.ref_count == 1

    # Permanently delete the file
    del_resp = await client.delete(f"/api/v1/files/{file_id}/permanent", headers=auth_headers)
    assert del_resp.status_code == 200

    # Verify ContentBlob record is completely removed from database
    blob_after = (await db_session.execute(select(ContentBlob).where(ContentBlob.checksum_sha256 == sha256))).scalar_one_or_none()
    assert blob_after is None


@pytest.mark.asyncio
async def test_empty_trash_bin(client: AsyncClient, auth_headers: dict):
    # 1. Create a folder and file, and a standalone file
    folder = (await client.post("/api/v1/folders/", json={"name": "TrashFolder"}, headers=auth_headers)).json()
    f_in_folder = (await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("inner.txt", io.BytesIO(b"Inner file"), "text/plain")},
        data={"folder_id": folder["id"]},
        headers=auth_headers,
    )).json()
    standalone_file = (await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("outer.txt", io.BytesIO(b"Outer file"), "text/plain")},
        headers=auth_headers,
    )).json()

    # 2. Soft-delete folder and standalone file
    await client.delete(f"/api/v1/folders/{folder['id']}", headers=auth_headers)
    await client.delete(f"/api/v1/files/{standalone_file['id']}", headers=auth_headers)

    # 3. Call empty trash endpoint
    empty_resp = await client.delete("/api/v1/files/trash/empty", headers=auth_headers)
    assert empty_resp.status_code == 200
    assert "Empty trash completed" in empty_resp.json()["message"]

    # 4. Check that both trash lists are completely empty
    trash_folders = (await client.get("/api/v1/folders/trash", headers=auth_headers)).json()
    trash_files = (await client.get("/api/v1/files/trash", headers=auth_headers)).json()
    assert len(trash_folders) == 0
    assert len(trash_files) == 0


@pytest.mark.asyncio
async def test_restore_all_from_trash(client: AsyncClient, auth_headers: dict):
    # 1. Create folder and file, and a standalone file
    folder = (await client.post("/api/v1/folders/", json={"name": "RestoreFolder"}, headers=auth_headers)).json()
    f_in_folder = (await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("child.txt", io.BytesIO(b"Child text"), "text/plain")},
        data={"folder_id": folder["id"]},
        headers=auth_headers,
    )).json()
    standalone = (await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("solo.txt", io.BytesIO(b"Solo text"), "text/plain")},
        headers=auth_headers,
    )).json()

    # 2. Soft-delete folder and standalone file
    await client.delete(f"/api/v1/folders/{folder['id']}", headers=auth_headers)
    await client.delete(f"/api/v1/files/{standalone['id']}", headers=auth_headers)

    # 3. Call restore-all endpoint
    restore_resp = await client.post("/api/v1/files/trash/restore-all", headers=auth_headers)
    assert restore_resp.status_code == 200
    assert "Restored 1 folders and 1 files from trash" in restore_resp.json()["message"]

    # 4. Check active directory access
    assert (await client.get(f"/api/v1/folders/{folder['id']}", headers=auth_headers)).status_code == 200
    assert (await client.get(f"/api/v1/files/{f_in_folder['id']}", headers=auth_headers)).status_code == 200
    assert (await client.get(f"/api/v1/files/{standalone['id']}", headers=auth_headers)).status_code == 200

    # 5. Trash lists should now be empty
    trash_folders = (await client.get("/api/v1/folders/trash", headers=auth_headers)).json()
    trash_files = (await client.get("/api/v1/files/trash", headers=auth_headers)).json()
    assert len(trash_folders) == 0
    assert len(trash_files) == 0


@pytest.mark.asyncio
async def test_files_search_and_file_type_filtering(client: AsyncClient, auth_headers: dict):
    # 1. Upload diverse files
    f_doc = (await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("project_report.pdf", io.BytesIO(b"PDF document content bytes"), "application/pdf")},
        headers=auth_headers,
    )).json()

    f_img = (await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("photo_vacation.jpg", io.BytesIO(b"\xff\xd8\xff\xe0\x00\x10JFIF image data"), "image/jpeg")},
        headers=auth_headers,
    )).json()

    f_vid = (await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("presentation_video.mp4", io.BytesIO(b"Video stream bytes here"), "video/mp4")},
        headers=auth_headers,
    )).json()

    # 2. Test search filter
    search_res = (await client.get("/api/v1/files/?search=vacation", headers=auth_headers)).json()
    assert len(search_res) == 1
    assert search_res[0]["id"] == f_img["id"]

    search_report = (await client.get("/api/v1/files/?search=report", headers=auth_headers)).json()
    assert len(search_report) == 1
    assert search_report[0]["id"] == f_doc["id"]

    # 3. Test file type filter
    doc_res = (await client.get("/api/v1/files/?file_type=document", headers=auth_headers)).json()
    assert any(f["id"] == f_doc["id"] for f in doc_res)
    assert not any(f["id"] == f_img["id"] for f in doc_res)

    img_res = (await client.get("/api/v1/files/?file_type=image", headers=auth_headers)).json()
    assert any(f["id"] == f_img["id"] for f in img_res)
    assert not any(f["id"] == f_vid["id"] for f in img_res)

    vid_res = (await client.get("/api/v1/files/?file_type=video", headers=auth_headers)).json()
    assert any(f["id"] == f_vid["id"] for f in vid_res)
    assert not any(f["id"] == f_doc["id"] for f in vid_res)


@pytest.mark.asyncio
async def test_files_sorting_by_name_size_date(client: AsyncClient, auth_headers: dict):
    # Upload 3 files of distinct sizes and alphabetical names
    f_a = (await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("alpha.txt", io.BytesIO(b"a" * 100), "text/plain")},
        headers=auth_headers,
    )).json()

    f_b = (await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("beta.txt", io.BytesIO(b"b" * 500), "text/plain")},
        headers=auth_headers,
    )).json()

    f_c = (await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("charlie.txt", io.BytesIO(b"c" * 300), "text/plain")},
        headers=auth_headers,
    )).json()

    # Sort by Name ASC
    res_name_asc = (await client.get("/api/v1/files/?sort_by=name&order=asc", headers=auth_headers)).json()
    names_asc = [f["name"] for f in res_name_asc]
    assert names_asc == sorted(names_asc)

    # Sort by Name DESC
    res_name_desc = (await client.get("/api/v1/files/?sort_by=name&order=desc", headers=auth_headers)).json()
    names_desc = [f["name"] for f in res_name_desc]
    assert names_desc == sorted(names_desc, reverse=True)

    # Sort by Size ASC
    res_size_asc = (await client.get("/api/v1/files/?sort_by=file_size&order=asc", headers=auth_headers)).json()
    sizes_asc = [f["file_size"] for f in res_size_asc]
    assert sizes_asc == sorted(sizes_asc)

    # Sort by Size DESC
    res_size_desc = (await client.get("/api/v1/files/?sort_by=file_size&order=desc", headers=auth_headers)).json()
    sizes_desc = [f["file_size"] for f in res_size_desc]
    assert sizes_desc == sorted(sizes_desc, reverse=True)


@pytest.mark.asyncio
async def test_trash_files_search_and_sort(client: AsyncClient, auth_headers: dict):
    # Create and delete files
    f1 = (await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("trash_apple.txt", io.BytesIO(b"Apple"), "text/plain")},
        headers=auth_headers,
    )).json()
    f2 = (await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("trash_banana.txt", io.BytesIO(b"Banana data long string"), "text/plain")},
        headers=auth_headers,
    )).json()

    await client.delete(f"/api/v1/files/{f1['id']}", headers=auth_headers)
    await client.delete(f"/api/v1/files/{f2['id']}", headers=auth_headers)

    # Search in trash
    search_res = (await client.get("/api/v1/files/trash?search=apple", headers=auth_headers)).json()
    assert len(search_res) == 1
    assert search_res[0]["id"] == f1["id"]

    # Sort trash by name ASC
    sort_res = (await client.get("/api/v1/files/trash?sort_by=name&order=asc", headers=auth_headers)).json()
    assert sort_res[0]["name"] <= sort_res[-1]["name"]


@pytest.mark.asyncio
async def test_file_preview_endpoint(client: AsyncClient, auth_headers: dict):
    # Upload a sample file for preview
    test_content = b"console.log('Testing preview endpoint');"
    upload_resp = await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("script.js", io.BytesIO(test_content), "application/javascript")},
        headers=auth_headers,
    )
    assert upload_resp.status_code == 201
    file_data = upload_resp.json()
    assert "preview_url" in file_data

    # Call preview endpoint
    preview_resp = await client.get(
        f"/api/v1/files/{file_data['id']}/preview",
        headers=auth_headers,
    )
    assert preview_resp.status_code == 200
    preview_data = preview_resp.json()
    assert preview_data["file_id"] == file_data["id"]
    assert preview_data["filename"] == "script.js"
    assert preview_data["file_size"] == len(test_content)
    assert preview_data["content_type"] == "application/javascript"
    assert "preview_url" in preview_data
    assert "download_url" in preview_data
    assert preview_data["expires_in"] == 3600

    # Stream content via preview URL to verify inline accessibility
    stream_resp = await client.get(preview_data["preview_url"])
    assert stream_resp.status_code == 200
    assert stream_resp.content == test_content

    # Verify 404 for non-existent file
    notFound_resp = await client.get(
        "/api/v1/files/nonexistent-uuid/preview",
        headers=auth_headers,
    )
    assert notFound_resp.status_code == 404


@pytest.mark.asyncio
async def test_rename_file_success_and_validation(client: AsyncClient, auth_headers: dict):
    # 1. Upload two files at root
    f1 = (await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("report.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf")},
        headers=auth_headers,
    )).json()

    f2 = (await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("summary.pdf", io.BytesIO(b"%PDF-1.4 test 2"), "application/pdf")},
        headers=auth_headers,
    )).json()

    # 2. Rename report.pdf -> annual_report.pdf
    patch_resp = await client.patch(
        f"/api/v1/files/{f1['id']}",
        json={"name": "annual_report.pdf"},
        headers=auth_headers,
    )
    assert patch_resp.status_code == 200
    updated = patch_resp.json()
    assert updated["name"] == "annual_report.pdf"

    # 3. Rename with empty or whitespace name -> 422
    empty_resp = await client.patch(
        f"/api/v1/files/{f1['id']}",
        json={"name": "    "},
        headers=auth_headers,
    )
    assert empty_resp.status_code == 422

    # 4. Rename to existing sibling name (summary.pdf) -> 422 duplicate error
    dup_resp = await client.patch(
        f"/api/v1/files/{f1['id']}",
        json={"name": "summary.pdf"},
        headers=auth_headers,
    )
    assert dup_resp.status_code == 422
    assert "already exists" in dup_resp.json()["error"]["message"]


@pytest.mark.asyncio
async def test_move_file_success_and_validation(client: AsyncClient, auth_headers: dict):
    # 1. Create a folder
    target_folder = (await client.post("/api/v1/folders/", json={"name": "ArchiveFolder"}, headers=auth_headers)).json()

    # 2. Upload file at root
    file_obj = (await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("data.csv", io.BytesIO(b"id,val\n1,10"), "text/csv")},
        headers=auth_headers,
    )).json()
    assert file_obj["folder_id"] is None

    # 3. Move file into ArchiveFolder
    move_resp = await client.patch(
        f"/api/v1/files/{file_obj['id']}",
        json={"folder_id": target_folder["id"]},
        headers=auth_headers,
    )
    assert move_resp.status_code == 200
    moved = move_resp.json()
    assert moved["folder_id"] == target_folder["id"]

    # 4. Move file back to root (folder_id: null)
    root_move_resp = await client.patch(
        f"/api/v1/files/{file_obj['id']}",
        json={"folder_id": None},
        headers=auth_headers,
    )
    assert root_move_resp.status_code == 200
    at_root = root_move_resp.json()
    assert at_root["folder_id"] is None

    # 5. Move into non-existent folder -> 404
    nf_resp = await client.patch(
        f"/api/v1/files/{file_obj['id']}",
        json={"folder_id": "nonexistent-folder-id"},
        headers=auth_headers,
    )
    assert nf_resp.status_code == 404


@pytest.mark.asyncio
async def test_restore_file_conflict_with_active_file(client: AsyncClient, auth_headers: dict):
    import io
    # 1. Upload file "notes.txt"
    up1 = (await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("notes.txt", io.BytesIO(b"old notes"), "text/plain")},
        headers=auth_headers,
    )).json()
    # 2. Delete it (to trash)
    await client.delete(f"/api/v1/files/{up1['id']}", headers=auth_headers)
    # 3. Upload new file "notes.txt" (active)
    up2 = (await client.post(
        "/api/v1/files/upload-direct",
        files={"file": ("notes.txt", io.BytesIO(b"new notes"), "text/plain")},
        headers=auth_headers,
    )).json()
    assert up2["id"] != up1["id"]
    # 4. Attempt to restore old notes.txt -> Should raise 409 Conflict
    res = await client.post(f"/api/v1/files/{up1['id']}/restore", headers=auth_headers)
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "FILE_ALREADY_EXISTS"




