from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from io import BytesIO

import openpyxl
from fastapi.testclient import TestClient

from hesabdar.config import Settings
from hesabdar.main import create_app
from tests.test_api import create_workspace, upload
from tests.test_operations import FILTER_TEXT, _download, _one, _xlsx

RESTORE_TEXT = "به نسخه اصلی برگرد"
COMMAND = "=cmd|'/c calc'!A0"


def test_restore_after_cleaning_matches_checksum_and_preview(client: TestClient) -> None:
    payload = _sheet_with_command()
    digest = hashlib.sha256(payload).hexdigest()
    workspace, stored = _one(client, "بازگشت", "فروش.xlsx", payload)
    applied = client.post(
        f"/api/workspaces/{workspace['id']}/cleanings",
        json={"file_id": stored["id"], "confirm": False},
    )
    assert applied.status_code == 201, applied.text
    assert applied.json()["result_version_id"] != stored["current_version_id"]
    history = client.get(f"/api/workspaces/{workspace['id']}/files/{stored['id']}/versions")
    assert history.status_code == 200, history.text
    versions = history.json()["versions"]
    assert [item["kind"] for item in versions] == ["original", "cleaned"]
    assert versions[1]["current"] is True
    restored = client.post(f"/api/workspaces/{workspace['id']}/versions/{stored['current_version_id']}/restore")
    assert restored.status_code == 200, restored.text
    body = restored.json()
    assert body["current_version_id"] == stored["current_version_id"]
    assert body["sha256"] == digest == stored["sha256"]
    downloaded = _download(client, workspace["id"], body["current_version_id"])
    assert downloaded == payload
    assert hashlib.sha256(downloaded).hexdigest() == digest
    preview = client.post(
        f"/api/workspaces/{workspace['id']}/inspections",
        json={"file_id": stored["id"]},
    )
    assert preview.status_code == 200, preview.text
    raws = _raws(preview.json())
    assert "علي" in raws
    assert "علی" not in raws
    assert COMMAND in raws
    book = openpyxl.load_workbook(BytesIO(downloaded))
    command = book.active["A6"]
    assert command.value == COMMAND
    assert command.data_type == "s"
    book.close()
    again = client.get(f"/api/workspaces/{workspace['id']}/files/{stored['id']}/versions")
    assert next(item["id"] for item in again.json()["versions"] if item["current"]) == stored["current_version_id"]


def test_other_workspace_cannot_restore_or_read(client: TestClient) -> None:
    payload = _sheet_with_command()
    first, stored = _one(client, "اول", "فروش.xlsx", payload)
    second = create_workspace(client, "دوم")
    foreign = client.post(f"/api/workspaces/{second['id']}/versions/{stored['current_version_id']}/restore")
    assert foreign.status_code == 404
    assert payload not in foreign.content
    own = client.get(f"/api/workspaces/{first['id']}/files/{stored['id']}")
    assert own.json()["current_version_id"] == stored["current_version_id"]
    assert own.json()["sha256"] == stored["sha256"]


def test_chat_restore_returns_the_original_checksum(client: TestClient) -> None:
    payload = _sheet_with_command()
    workspace, stored = _one(client, "گفتگو", "فروش.xlsx", payload)
    client.post(
        f"/api/workspaces/{workspace['id']}/cleanings",
        json={"file_id": stored["id"], "confirm": False},
    )
    response = client.post(
        f"/api/workspaces/{workspace['id']}/operations",
        json={"text": RESTORE_TEXT, "file_ids": [stored["id"]]},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["plan"]["goal"] == "restore_version"
    assert body["change"]["sha256_after"] == stored["sha256"]
    assert body["change"]["sha256_before"] != stored["sha256"]
    assert _download(client, workspace["id"], body["outputs"][0]["version_id"]) == payload


def test_filter_change_report_counts_rows(client: TestClient) -> None:
    rows = [
        ["نام", "مبلغ"],
        ["علی", 60000000],
        ["سارا", 50000000],
        ["رضا", 40000000],
        ["نیکا", 51000000],
        ["هدی", 1000],
        [COMMAND, 70000000],
    ]
    payload = _xlsx(rows)
    workspace, stored = _one(client, "گزارش تغییر", "فروش.xlsx", payload)
    response = client.post(
        f"/api/workspaces/{workspace['id']}/operations",
        json={"text": FILTER_TEXT, "file_ids": [stored["id"]]},
    )
    assert response.status_code == 201, response.text
    change = response.json()["change"]
    assert change["rows_before"] == 6
    assert change["rows_after"] == 3
    assert change["columns_before"] == 2
    assert change["columns_after"] == 2
    assert change["sheets_before"] == 1
    assert change["sheets_after"] == 1
    assert change["sha256_before"] == stored["sha256"]


def test_restart_does_not_call_an_interrupted_operation_successful(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", host="127.0.0.1")
    with TestClient(create_app(settings)) as client:
        workspace = create_workspace(client, "ناتمام")
    operation_id = str(uuid.uuid4())
    record = {
        "id": operation_id,
        "status": "running",
        "progress_current": 1,
        "progress_total": 2,
        "progress_label": "در حال فیلتر",
        "summary": "2 ردیف از 4 ردیف مبلغشان بیشتر از 50000000 بود.",
        "warnings": [],
        "error": None,
        "outputs": [{"file_id": str(uuid.uuid4()), "version_id": str(uuid.uuid4()), "name": "فیلتر.xlsx"}],
        "cards": [],
        "charts": [],
        "evaluation": None,
        "change": None,
        "plan": {
            "id": operation_id,
            "workspace_id": workspace["id"],
            "goal": "filter",
            "user_text": FILTER_TEXT,
            "steps": [],
            "ambiguities": [],
            "source": "rules",
        },
        "llm_status": "پیکربندی نشده",
        "pending": None,
        "created_at": "2026-01-01T00:00:00Z",
        "finished_at": "2026-01-01T00:00:00Z",
    }
    database = sqlite3.connect(settings.data_dir / "hesabdar.sqlite")
    database.execute(
        """
        INSERT INTO operations (
            id, workspace_id, status, plan_json, summary, created_at, finished_at, error_code, error_message
        ) VALUES (?, ?, 'running', ?, ?, ?, ?, NULL, NULL)
        """,
        (
            operation_id,
            workspace["id"],
            json.dumps(record, ensure_ascii=False),
            record["summary"],
            record["created_at"],
            record["finished_at"],
        ),
    )
    database.commit()
    database.close()
    with TestClient(create_app(settings)) as client:
        response = client.get(f"/api/workspaces/{workspace['id']}/operations/{operation_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "failed"
    assert body["status"] != "succeeded"
    assert body["outputs"] == []
    assert body["summary"] is None
    assert body["error"]["message"] == "عملیات ناتمام ماند."


def _sheet_with_command() -> bytes:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "فروش"
    rows = [
        ["نام", "مبلغ"],
        ["علي", 10],
        ["سارا", 20],
        ["رضا", 30],
        ["نیکا", 40],
        [COMMAND, 50],
    ]
    for row in rows:
        sheet.append(row)
    cell = sheet["A6"]
    cell.value = COMMAND
    cell.data_type = "s"
    cell.number_format = "@"
    buffer = BytesIO()
    book.save(buffer)
    book.close()
    return buffer.getvalue()


def _raws(report: dict) -> list[str]:
    found = []
    for sheet in report["sheets"]:
        for row in sheet["preview"]["rows"]:
            for cell in row:
                if cell.get("raw"):
                    found.append(cell["raw"])
    return found
