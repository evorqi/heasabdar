from __future__ import annotations

import hashlib
import sqlite3
from urllib.parse import quote

from fastapi.testclient import TestClient

from hesabdar.config import DEFAULT_MAX_FILES, DEFAULT_MAX_UPLOAD_BYTES, DEFAULT_MAX_UNCOMPRESSED_BYTES, Settings
from hesabdar.main import create_app
from hesabdar.messages import FILE_CORRUPT_EXCEL
from tests.samples import make_csv, make_xls, make_xlsx


def create_workspace(client: TestClient, title: str = "فروش مهر") -> dict:
    response = client.post("/api/workspaces", json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()


def upload(client: TestClient, workspace_id: str, parts: list[tuple[str, bytes]]):
    files = [("files", (name, data, "application/octet-stream")) for name, data in parts]
    return client.post(f"/api/workspaces/{workspace_id}/files", files=files)


def test_default_limits_are_the_design_targets() -> None:
    settings = Settings(data_dir=__import__("pathlib").Path("data"))
    assert settings.max_upload_bytes == DEFAULT_MAX_UPLOAD_BYTES == 30 * 1024 * 1024
    assert settings.max_uncompressed_bytes == DEFAULT_MAX_UNCOMPRESSED_BYTES == 200 * 1024 * 1024
    assert settings.max_files_per_upload == DEFAULT_MAX_FILES == 20


def test_workspace_flow_and_no_public_listing(client: TestClient) -> None:
    assert client.get("/api/workspaces").status_code == 404
    created = create_workspace(client, "  فروش شعبه تهران  ")
    assert created["title"] == "فروش شعبه تهران"
    assert created["file_count"] == 0
    fetched = client.get(f"/api/workspaces/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "فروش شعبه تهران"
    missing = client.get("/api/workspaces/not-a-uuid")
    assert missing.status_code == 404
    assert "data/" not in missing.text


def test_title_is_stored_as_data_not_sql(client: TestClient) -> None:
    title = "'; DROP TABLE workspaces; --"
    created = create_workspace(client, title)
    again = client.get(f"/api/workspaces/{created['id']}")
    assert again.status_code == 200
    assert again.json()["title"] == title


def test_accepts_three_formats_in_one_request(client: TestClient, settings: Settings) -> None:
    workspace = create_workspace(client)
    csv_bytes = make_csv()
    xlsx_bytes = make_xlsx()
    xls_bytes = make_xls()
    response = upload(
        client,
        workspace["id"],
        [
            ("گزارش فروش مهر.csv", csv_bytes),
            ("book.xlsx", xlsx_bytes),
            ("legacy.xls", xls_bytes),
        ],
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["rejected"] == []
    names = {item["original_name"] for item in body["accepted"]}
    assert names == {"گزارش فروش مهر.csv", "book.xlsx", "legacy.xls"}
    persian = next(item for item in body["accepted"] if item["original_name"].endswith(".csv"))
    assert persian["original_name"][0] == "گ"
    assert persian["format"] == "csv"
    assert persian["status"] == "stored"
    assert persian["sha256"] == hashlib.sha256(csv_bytes).hexdigest()

    listed = client.get(f"/api/workspaces/{workspace['id']}/files")
    assert listed.status_code == 200
    listed_names = {item["original_name"] for item in listed.json()["files"]}
    assert listed_names == names

    downloaded = client.get(
        f"/api/workspaces/{workspace['id']}/versions/{persian['current_version_id']}/download"
    )
    assert downloaded.status_code == 200
    assert downloaded.content == csv_bytes
    header = downloaded.headers["content-disposition"]
    assert quote("گزارش فروش مهر.csv") in header
    assert "\r" not in header and "\n" not in header
    blob = (
        settings.data_dir / "blobs" / workspace["id"] / persian["current_version_id"]
    )
    assert blob.read_bytes() == csv_bytes
    assert blob.read_bytes() == downloaded.content
    for path in settings.data_dir.rglob("*"):
        if path.is_file():
            assert "گزارش" not in path.name

    connection = sqlite3.connect(settings.data_dir / "hesabdar.sqlite")
    version = connection.execute(
        "SELECT kind, parent_version_id, row_count, note, operation_id FROM versions WHERE id = ?",
        (persian["current_version_id"],),
    ).fetchone()
    assert version == ("original", None, None, "نسخه اصلی بارگذاری‌شده", None)
    operations = connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0]
    assert operations == 0


def test_partial_batch_and_fake_extension(client: TestClient) -> None:
    workspace = create_workspace(client)
    secret = "SECRET_CELL_VALUE_9f3a"
    response = upload(
        client,
        workspace["id"],
        [
            ("درست.csv", make_csv()),
            ("جعلی.xlsx", secret.encode("utf-8")),
            ("scan.pdf", b"%PDF-1.4"),
        ],
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert [item["original_name"] for item in body["accepted"]] == ["درست.csv"]
    codes = {item["code"] for item in body["rejected"]}
    assert codes == {"file.corrupt", "file.unsupported_type"}
    corrupt = next(item for item in body["rejected"] if item["filename"].endswith(".xlsx"))
    assert corrupt["message"] == FILE_CORRUPT_EXCEL
    assert secret not in response.text

    only_bad = upload(client, workspace["id"], [("bad.xlsx", secret.encode("utf-8"))])
    assert only_bad.status_code == 400
    assert only_bad.json()["message"] == "هیچ فایلی ذخیره نشد."
    assert secret not in only_bad.text


def test_empty_traversal_and_size_limits(tmp_path, client: TestClient, settings: Settings) -> None:
    workspace = create_workspace(client)
    empty = upload(client, workspace["id"], [("empty.csv", b"")])
    assert empty.status_code == 400
    assert empty.json()["detail"]["rejected"][0]["code"] == "file.empty"

    traversal = upload(client, workspace["id"], [("../راز.csv", make_csv())])
    assert traversal.status_code == 400
    assert traversal.json()["detail"]["rejected"][0]["code"] == "file.invalid_name"
    assert not any(path.name == "راز.csv" for path in settings.data_dir.rglob("*"))
    assert not (tmp_path / "راز.csv").exists()

    tight = Settings(data_dir=tmp_path / "tight", host="127.0.0.1", max_upload_bytes=32)
    with TestClient(create_app(tight)) as tight_client:
        created = create_workspace(tight_client)
        oversized = b"name,amount\n" + (b"x,1\n" * 20)
        assert len(oversized) > 32
        response = upload(tight_client, created["id"], [("big.csv", oversized)])
        assert response.status_code == 400
        assert response.json()["detail"]["rejected"][0]["code"] == "file.too_large"
        assert "32 بایت" in response.json()["detail"]["rejected"][0]["message"]


def test_cross_workspace_is_not_readable(client: TestClient) -> None:
    first = create_workspace(client, "اول")
    second = create_workspace(client, "دوم")
    stored = upload(client, first["id"], [("مشتریان.csv", make_csv())])
    item = stored.json()["accepted"][0]
    foreign_file = client.get(f"/api/workspaces/{second['id']}/files/{item['id']}")
    foreign_download = client.get(
        f"/api/workspaces/{second['id']}/versions/{item['current_version_id']}/download"
    )
    assert foreign_file.status_code == 404
    assert foreign_download.status_code == 404
    assert make_csv() not in foreign_download.content
    own = client.get(
        f"/api/workspaces/{first['id']}/versions/{item['current_version_id']}/download"
    )
    assert own.content == make_csv()


def test_zip_slip_stays_inside_the_blob(client: TestClient, settings: Settings) -> None:
    workspace = create_workspace(client)
    payload = make_xlsx(extra_name="../escaped.txt", extra_payload=b"nope")
    response = upload(client, workspace["id"], [("کتاب.xlsx", payload)])
    assert response.status_code == 201, response.text
    names = {path.name for path in settings.data_dir.rglob("*")}
    assert "escaped.txt" not in names
    version_id = response.json()["accepted"][0]["current_version_id"]
    blob = settings.data_dir / "blobs" / workspace["id"] / version_id
    assert blob.read_bytes() == payload


def test_original_blob_is_not_replaced(client: TestClient, settings: Settings) -> None:
    workspace = create_workspace(client)
    first = upload(client, workspace["id"], [("a.csv", b"id,name\n1,a\n")])
    item = first.json()["accepted"][0]
    blob = settings.data_dir / "blobs" / workspace["id"] / item["current_version_id"]
    before = blob.read_bytes()
    second = upload(client, workspace["id"], [("a.csv", b"id,name\n2,b\n")])
    assert second.status_code == 201
    assert blob.read_bytes() == before
    assert second.json()["accepted"][0]["id"] != item["id"]


def test_validation_error_hides_payload(client: TestClient) -> None:
    response = client.post(
        "/api/workspaces",
        content=b'{"title": "SECRET_CELL_VALUE_9f3a"',
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400
    assert "SECRET_CELL_VALUE_9f3a" not in response.text
    assert response.json()["message"] == "درخواست نامعتبر است."
