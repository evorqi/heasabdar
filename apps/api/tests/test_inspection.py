from __future__ import annotations

import hashlib
import sqlite3

from fastapi.testclient import TestClient

from hesabdar.config import Settings
from hesabdar.inspection.build import build_report
from hesabdar.inspection.classify import CellView
from hesabdar.inspection.readers import RawSheet, WorkbookRead
from hesabdar.messages import FILE_CORRUPT_EXCEL, WORKBOOK_PARTIAL
from tests.samples import make_xlsx
from tests.test_api import create_workspace, upload
from tests.test_operations import SORT_TEXT
from tests.workbooks import (
    ERROR_TOKENS,
    broken_row_workbook,
    error_workbook,
    flagged_workbook,
    persian_csv,
    persian_xls,
    pivot_workbook,
    sales_workbook,
    style_index_workbook,
)


def inspect(client: TestClient, workspace_id: str, file_id: str):
    return client.post(
        f"/api/workspaces/{workspace_id}/inspections",
        json={"file_id": file_id},
    )


def store(client: TestClient, workspace_id: str, name: str, data: bytes) -> dict:
    response = upload(client, workspace_id, [(name, data)])
    assert response.status_code == 201, response.text
    return response.json()["accepted"][0]


def test_persian_workbook_structure_roles_and_immutable_blob(
    client: TestClient, settings: Settings
) -> None:
    original = sales_workbook()
    workspace = create_workspace(client)
    stored = store(client, workspace["id"], "فروش مهر.xlsx", original)
    blob = settings.data_dir / "blobs" / workspace["id"] / stored["current_version_id"]
    assert hashlib.sha256(blob.read_bytes()).hexdigest() == hashlib.sha256(original).hexdigest()

    response = inspect(client, workspace["id"], stored["id"])
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["format"] == "xlsx"
    assert report["sheet_count"] == 3
    assert [sheet["name"] for sheet in report["sheets"]] == ["فروش", "هزینه‌ها", "خالی"]

    sales = report["sheets"][0]
    assert sales["row_count"] == 3
    assert sales["data_row_count"] == 2
    assert sales["column_count"] == 5
    assert sales["header_status"] == "detected"
    assert sales["formula_count"] == 1
    names = [column["name"] for column in sales["columns"]]
    assert names == ["نام", "کد ملی", "مبلغ", "تاریخ", "محاسبه"]

    national_id = sales["columns"][1]
    assert national_id["kind"] == "identifier"
    assert national_id["role_hints"] == ["national_id"]
    assert national_id["kind"] != "number"
    amount = sales["columns"][2]
    assert amount["role_hints"] == ["amount"]
    assert amount["kind"] == "number"
    assert sales["columns"][3]["role_hints"] == ["date"]
    assert sales["columns"][3]["kind"] == "date"

    assert sales["preview"]["rows"][0][1] == {
        "raw": "0012345678",
        "parsed": None,
        "warnings": [],
    }
    assert sales["preview"]["rows"][1][1]["raw"] == "0123456789"
    assert sales["preview"]["rows"][0][2]["raw"] == "1500000"
    assert sales["preview"]["rows"][0][4]["raw"] == "=C2*2"
    assert sales["preview"]["rows"][0][4]["parsed"] is None

    costs = report["sheets"][1]
    assert costs["row_count"] == 2
    assert costs["data_row_count"] == 1
    assert costs["column_count"] == 2
    empty = report["sheets"][2]
    assert empty["data_row_count"] == 0
    assert empty["row_count"] == 0

    codes = {(item["severity"], item["code"]) for item in report["findings"]}
    assert ("info", "column.identifier") in codes
    assert ("error", "date.invalid") in codes
    assert ("error", "excel.error") in codes
    assert ("info", "sheet.no_data") in codes
    identifier_notes = [
        item for item in report["findings"] if item["code"] == "column.identifier"
    ]
    assert any("شناسه" in item["message"] and "نه عدد" in item["message"] for item in identifier_notes)
    assert any(item["message"] == "نتیجه فرمول ارزیابی نشده است." for item in report["unchecked"])
    assert not any(item["code"] == "formula.not_evaluated" and item["severity"] == "info" for item in report["findings"])

    assert blob.read_bytes() == original
    downloaded = client.get(
        f"/api/workspaces/{workspace['id']}/versions/{stored['current_version_id']}/download"
    )
    assert downloaded.content == original

    with sqlite3.connect(settings.data_dir / "hesabdar.sqlite") as db:
        version = db.execute(
            "SELECT row_count, sheet_count FROM versions WHERE id = ?",
            (stored["current_version_id"],),
        ).fetchone()
        version_count = db.execute("SELECT COUNT(*) FROM versions").fetchone()[0]
    assert version == (3, 3)
    assert version_count == 1

    other = create_workspace(client, "فضای دیگر")
    hidden = inspect(client, other["id"], stored["id"])
    assert hidden.status_code == 404
    assert stored["id"] not in hidden.text
    assert "0012345678" not in hidden.text


def test_visible_formula_errors_are_not_successful_evaluations(client: TestClient) -> None:
    workspace = create_workspace(client)
    stored = store(client, workspace["id"], "خطاها.xlsx", error_workbook())
    response = inspect(client, workspace["id"], stored["id"])
    assert response.status_code == 200, response.text
    report = response.json()
    seen = {item["evidence"]["token"] for item in report["findings"] if item["code"] == "excel.error"}
    assert seen == set(ERROR_TOKENS)
    div = next(item for item in report["findings"] if item.get("evidence", {}).get("token") == "#DIV/0!")
    assert "\u2066#DIV/0!\u2069" in div["message"]
    unchecked = report["unchecked"]
    assert len(unchecked) == 1
    assert unchecked[0]["code"] == "formula.not_evaluated"
    assert unchecked[0]["message"] == "نتیجه فرمول ارزیابی نشده است."
    assert unchecked[0]["count"] == 1
    assert report["sheets"][0]["formula_count"] == 1
    assert report["sheets"][0]["error_display_count"] == len(ERROR_TOKENS)


def test_macro_and_pivot_are_reported_without_rewriting(
    client: TestClient, settings: Settings
) -> None:
    original = flagged_workbook()
    workspace = create_workspace(client)
    stored = store(client, workspace["id"], "ماکرو.xlsx", original)
    response = inspect(client, workspace["id"], stored["id"])
    assert response.status_code == 200, response.text
    report = response.json()
    flags = {item["evidence"]["flag"] for item in report["findings"] if item["code"].startswith("structure.")}
    assert {"macro", "pivot_table"} <= flags
    assert "macro" in report["sheets"][0]["unsupported"]
    assert "pivot_table" in report["sheets"][0]["unsupported"]
    blob = settings.data_dir / "blobs" / workspace["id"] / stored["current_version_id"]
    assert blob.read_bytes() == original


def test_unreadable_excel_parts_keep_sheet_values(client: TestClient, settings: Settings) -> None:
    workspace = create_workspace(client)
    original = pivot_workbook()
    stored = store(client, workspace["id"], "سنگین.xlsx", original)
    response = inspect(client, workspace["id"], stored["id"])
    assert response.status_code == 200, response.text
    report = response.json()
    sales = report["sheets"][0]
    assert sales["name"] == "فروش"
    assert sales["columns"][0]["name"] == "نام"
    assert sales["preview"]["rows"][0][0]["raw"] == "علی"
    assert sales["preview"]["rows"][0][1]["raw"] == "15000000"
    assert sales["preview"]["rows"][0][2]["raw"] == "=B2*2"
    flags = {item["evidence"]["flag"] for item in report["findings"] if item["code"].startswith("structure.")}
    assert "pivot_table" in flags
    partial = [item for item in report["unchecked"] if item["code"] == "workbook.partial_read"]
    assert len(partial) == 1
    assert partial[0]["message"] == WORKBOOK_PARTIAL
    assert "workbook.xml" not in response.text
    assert str(settings.data_dir) not in response.text
    blob = settings.data_dir / "blobs" / workspace["id"] / stored["current_version_id"]
    assert blob.read_bytes() == original

    sorted_file = client.post(
        f"/api/workspaces/{workspace['id']}/operations",
        json={"text": SORT_TEXT, "file_ids": [stored["id"]]},
    )
    assert sorted_file.status_code == 201, sorted_file.text
    body = sorted_file.json()
    assert body["status"] == "succeeded"
    assert body["error"] is None
    assert FILE_CORRUPT_EXCEL not in sorted_file.text
    assert blob.read_bytes() == original

    for builder in (style_index_workbook, broken_row_workbook):
        payload = builder()
        kept = store(client, workspace["id"], "فروش.xlsx", payload)
        inspected = inspect(client, workspace["id"], kept["id"])
        assert inspected.status_code == 200, inspected.text
        sheet = inspected.json()["sheets"][0]
        assert sheet["columns"][0]["name"] == "نام"
        assert sheet["preview"]["rows"][0][0]["raw"] == "علی"
        assert sheet["preview"]["rows"][0][1]["raw"] == "15000000"
        assert any(item["message"] == WORKBOOK_PARTIAL for item in inspected.json()["unchecked"])
        kept_blob = settings.data_dir / "blobs" / workspace["id"] / kept["current_version_id"]
        assert kept_blob.read_bytes() == payload


def test_corrupt_excel_is_rejected_without_leaking_bytes(client: TestClient, settings: Settings) -> None:
    original = make_xlsx()
    workspace = create_workspace(client)
    stored = store(client, workspace["id"], "خراب.xlsx", original)
    response = inspect(client, workspace["id"], stored["id"])
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "file.corrupt"
    assert body["message"] == FILE_CORRUPT_EXCEL
    assert "workbook.xml" not in response.text
    assert str(settings.data_dir) not in response.text
    blob = settings.data_dir / "blobs" / workspace["id"] / stored["current_version_id"]
    assert blob.read_bytes() == original


def test_persian_csv_keeps_identifier_text(client: TestClient) -> None:
    workspace = create_workspace(client)
    stored = store(client, workspace["id"], "مشتری.csv", persian_csv())
    response = inspect(client, workspace["id"], stored["id"])
    assert response.status_code == 200, response.text
    sheet = response.json()["sheets"][0]
    assert sheet["name"] == "مشتری"
    assert sheet["row_count"] == 2
    assert sheet["column_count"] == 3
    assert sheet["data_row_count"] == 1
    national_id = sheet["columns"][1]
    amount = sheet["columns"][2]
    assert national_id["kind"] == "identifier"
    assert national_id["role_hints"] == ["national_id"]
    assert amount["role_hints"] == ["amount"]
    assert amount["kind"] == "number"
    preview = sheet["preview"]["rows"][0]
    assert preview[0]["raw"] == "علی‌رضا"
    assert preview[1] == {"raw": "۰۰۱۲۳۴۵۶۷۸", "parsed": None, "warnings": []}
    assert preview[2]["raw"] == "۱۲۳۴"
    assert preview[2]["parsed"] == "1234"


def test_xls_reads_text_identifier_and_marks_formulas_unchecked(client: TestClient) -> None:
    workspace = create_workspace(client)
    stored = store(client, workspace["id"], "قدیمی.xls", persian_xls())
    response = inspect(client, workspace["id"], stored["id"])
    assert response.status_code == 200, response.text
    report = response.json()
    sheet = report["sheets"][0]
    assert sheet["name"] == "فروش"
    assert sheet["row_count"] == 2
    assert sheet["column_count"] == 3
    assert sheet["data_row_count"] == 1
    assert sheet["columns"][1]["kind"] == "identifier"
    assert sheet["preview"]["rows"][0][1]["raw"] == "0012345678"
    assert sheet["preview"]["rows"][0][1]["parsed"] is None
    assert report["unchecked"][0]["code"] == "formula.text_unavailable"
    assert "xls" in report["unchecked"][0]["message"]


def test_ambiguous_and_currency_values_stay_honest() -> None:
    sheet = RawSheet(
        name="برگه",
        rows=[
            [CellView("تاریخ"), CellView("مبلغ"), CellView("عدد")],
            [CellView("02/03/04"), CellView("۱٬۲۰۰ ریال"), CellView("1,234")],
            [CellView("1403/07/01"), CellView("۱۲۰۰ تومان"), CellView("10")],
        ],
    )
    report = build_report(WorkbookRead([sheet], [], []), "file", "version", "csv")
    columns = report["sheets"][0]["columns"]
    assert columns[0]["kind"] == "date"
    assert columns[1]["kind"] == "currency"
    assert columns[1]["role_hints"] == ["amount"]
    assert columns[2]["kind"] == "mixed"
    preview = report["sheets"][0]["preview"]["rows"]
    assert preview[0][0]["parsed"] is None
    assert "date.ambiguous" in preview[0][0]["warnings"]
    assert preview[0][2]["parsed"] is None
    assert "number.ambiguous" in preview[0][2]["warnings"]
    assert preview[0][1]["raw"] == "۱٬۲۰۰ ریال"
    assert preview[0][1]["parsed"] == "1200"
    assert preview[1][1]["parsed"] == "1200"
    codes = {item["code"] for item in report["findings"]}
    assert "date.ambiguous" in codes
    assert "number.ambiguous" in codes


def test_pattern_only_national_id_is_a_hypothesis_not_a_number() -> None:
    rows = [[CellView("ردیف")]] + [[CellView(f"{index:010d}")] for index in range(1, 9)]
    sheet = RawSheet(name="برگه", rows=rows)
    report = build_report(WorkbookRead([sheet], [], []), "file", "version", "xlsx")
    column = report["sheets"][0]["columns"][0]
    assert column["kind"] == "identifier"
    assert column["role_hints"] == ["national_id"]
    assert report["sheets"][0]["preview"]["rows"][0][0]["parsed"] is None
    hypotheses = [item for item in report["findings"] if item["code"] == "column.role_hypothesis"]
    assert hypotheses
    assert hypotheses[0]["severity"] == "hypothesis"
    assert all(item["code"] != "column.identifier" for item in report["findings"])


def test_outlier_is_a_hypothesis() -> None:
    rows = [[CellView("مبلغ")]] + [[CellView(str(value))] for value in (10, 10, 10, 10, 10, 10, 10, 500)]
    sheet = RawSheet(name="فروش", rows=rows)
    report = build_report(WorkbookRead([sheet], [], []), "file", "version", "xlsx")
    outliers = [item for item in report["findings"] if item["code"] == "value.outlier"]
    assert len(outliers) == 1
    assert outliers[0]["severity"] == "hypothesis"
    assert "ثابت نمی‌کند" in outliers[0]["message"]


def test_preview_stops_at_two_hundred_rows() -> None:
    rows = [[CellView("مبلغ")]] + [[CellView(str(index))] for index in range(201)]
    sheet = RawSheet(name="فروش", rows=rows)
    report = build_report(WorkbookRead([sheet], [], []), "file", "version", "csv")
    built = report["sheets"][0]
    assert built["data_row_count"] == 201
    assert built["row_count"] == 202
    assert len(built["preview"]["rows"]) == 200
    assert built["preview"]["truncated"] is True
