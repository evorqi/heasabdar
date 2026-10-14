from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from hesabdar.db import Database
from hesabdar.errors import AppError
from hesabdar.files.service import FileService
from hesabdar.files.workbook import write_workbook
from hesabdar.inspection.build import build_report
from hesabdar.inspection.readers import read_workbook
from hesabdar.validation.limits import assert_complete
from hesabdar.messages import (
    RECONCILE_INVALID,
    RECONCILE_KEY_MISSING,
    RECONCILE_PREVIEW,
    RECONCILE_QUESTION,
    RECONCILE_SAME_FILE,
    RECONCILE_SUCCEEDED,
    RECONCILE_WAITING,
    REQUEST_INVALID,
)
from hesabdar.reconcile.engine import load_table, reconcile, suggest_keys
from hesabdar.reconcile.output import SHEET_NAMES, SUMMARY_LABELS, build_sheets

_GUARD = threading.Lock()
_LOCKS: dict[str, threading.Lock] = {}
_MAX_KEY_COLUMNS = 8
_MAX_COLUMN_NAME = 200


class ReconcileService:
    def __init__(self, files: FileService, database: Database) -> None:
        self.files = files
        self.database = database

    def preview(self, workspace_id: str, left_file_id: str, right_file_id: str) -> dict:
        left_meta, left, right_meta, right = self._tables(workspace_id, left_file_id, right_file_id)
        suggestion = suggest_keys(left, right)
        if suggestion["ambiguous"]:
            return _public(
                left_meta,
                right_meta,
                left,
                right,
                status="preview",
                key_columns=[],
                key_decision=None,
                suggestion=suggestion,
                result=None,
                message=RECONCILE_QUESTION,
            )
        result = reconcile(left, right, suggestion["keys"])
        _raise_if_broken(result)
        return _public(
            left_meta,
            right_meta,
            left,
            right,
            status="preview",
            key_columns=suggestion["keys"],
            key_decision="detected",
            suggestion=suggestion,
            result=result,
            message=RECONCILE_PREVIEW,
        )

    def apply(
        self,
        workspace_id: str,
        left_file_id: str,
        right_file_id: str,
        key_columns: list[str] | None,
    ) -> dict:
        with _workspace_lock(workspace_id):
            left_meta, left, right_meta, right = self._tables(workspace_id, left_file_id, right_file_id)
            suggestion = suggest_keys(left, right)
            chosen = [name.strip() for name in (key_columns or []) if name and name.strip()]
            if chosen:
                _check_key_names(chosen)
                decision = "confirmed_by_user"
                columns = chosen
            elif suggestion["ambiguous"]:
                report = _public(
                    left_meta,
                    right_meta,
                    left,
                    right,
                    status="waiting_confirmation",
                    key_columns=[],
                    key_decision=None,
                    suggestion=suggestion,
                    result=None,
                    message=RECONCILE_WAITING,
                )
                self._store(workspace_id, report, None)
                return report
            else:
                decision = "detected"
                columns = list(suggestion["keys"])
            result = reconcile(left, right, columns)
            _raise_if_broken(result)
            report = _public(
                left_meta,
                right_meta,
                left,
                right,
                status="succeeded",
                key_columns=columns,
                key_decision=decision,
                suggestion=suggestion,
                result=result,
                message=RECONCILE_SUCCEEDED,
            )
            data = write_workbook(build_sheets(report), "xlsx")
            if not _matches(data, report):
                raise AppError("output.invalid", RECONCILE_INVALID, 422)
            operation_id = str(uuid.uuid4())
            stored = self.files.add_output_file(
                workspace_id,
                "مغایرت.xlsx",
                data,
                kind="reconciled",
                note="فایل مغایرت",
                parent_version_id=left_meta["current_version_id"],
                operation_id=operation_id,
                row_count=result["validation"]["left_rows"] + result["validation"]["right_rows"],
                sheet_count=len(SHEET_NAMES),
            )
            report["result_file_id"] = stored["id"]
            report["result_version_id"] = stored["current_version_id"]
            report["result_name"] = stored["original_name"]
            self._store(workspace_id, report, operation_id)
            return report

    def _tables(self, workspace_id: str, left_file_id: str, right_file_id: str):
        if left_file_id == right_file_id:
            raise AppError("request.invalid", RECONCILE_SAME_FILE, 400)
        left_meta = self.files.get_file(workspace_id, left_file_id)
        right_meta = self.files.get_file(workspace_id, right_file_id)
        left = _table(self.files, workspace_id, left_meta)
        right = _table(self.files, workspace_id, right_meta)
        return left_meta, left, right_meta, right

    def _store(self, workspace_id: str, report: dict, operation_id: str | None) -> None:
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.database.transaction() as conn:
            if operation_id is not None:
                conn.execute(
                    """
                    INSERT INTO operations (
                        id, workspace_id, status, plan_json, summary, created_at, finished_at,
                        error_code, error_message
                    ) VALUES (?, ?, ?, NULL, ?, ?, ?, NULL, NULL)
                    """,
                    (
                        operation_id,
                        workspace_id,
                        report["status"],
                        report["message"],
                        created_at,
                        created_at,
                    ),
                )
            conn.execute(
                """
                INSERT INTO reconciliations (
                    id, workspace_id, left_file_id, right_file_id, result_file_id,
                    status, report_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    workspace_id,
                    report["left_file_id"],
                    report["right_file_id"],
                    report["result_file_id"],
                    report["status"],
                    json.dumps(report, ensure_ascii=False),
                    created_at,
                ),
            )


def _table(files: FileService, workspace_id: str, meta: dict) -> dict:
    _record, data = files.read_version(workspace_id, meta["current_version_id"])
    read = read_workbook(data, meta["format"], meta["original_name"])
    assert_complete(read)
    built = build_report(read, meta["id"], meta["current_version_id"], meta["format"])
    if not built["sheets"]:
        raise AppError("request.invalid", REQUEST_INVALID, 400)
    summary = max(built["sheets"], key=lambda sheet: sheet["data_row_count"])
    raw = next(sheet for sheet in read.sheets if sheet.name == summary["name"])
    return load_table(raw, summary)


def _public(
    left_meta: dict,
    right_meta: dict,
    left: dict,
    right: dict,
    *,
    status: str,
    key_columns: list[str],
    key_decision: str | None,
    suggestion: dict,
    result: dict | None,
    message: str,
) -> dict:
    rows = []
    summary = {name: 0 for name in ("full_match", "value_mismatch", "only_left", "only_right", "ambiguous")}
    validation = {
        "ok": False,
        "left_rows": len(left["rows"]),
        "right_rows": len(right["rows"]),
        "identity_left": 0,
        "identity_right": 0,
        "left_amount": None,
        "right_amount": None,
        "scale": None,
    }
    if result is not None:
        rows = [_public_row(left, right, row) for row in result["rows"]]
        summary = result["summary"]
        validation = {
            "ok": result["validation"]["ok"],
            "left_rows": result["validation"]["left_rows"],
            "right_rows": result["validation"]["right_rows"],
            "identity_left": result["validation"]["identity_left"],
            "identity_right": result["validation"]["identity_right"],
            "left_amount": result["validation"]["left_amount"],
            "right_amount": result["validation"]["right_amount"],
            "scale": result["validation"]["scale"],
        }
    return {
        "status": status,
        "message": message,
        "left_file_id": left_meta["id"],
        "right_file_id": right_meta["id"],
        "left_version_id": left_meta["current_version_id"],
        "right_version_id": right_meta["current_version_id"],
        "result_file_id": None,
        "result_version_id": None,
        "result_name": None,
        "key_columns": key_columns,
        "key_decision": key_decision,
        "key_ambiguous": suggestion["ambiguous"],
        "key_choices": suggestion["choices"],
        "question": RECONCILE_QUESTION if suggestion["ambiguous"] else None,
        "rows": rows,
        "summary": summary,
        "validation": validation,
    }


def _public_row(left: dict, right: dict, row: dict) -> dict:
    left_values = left["rows"][row["left_index"]] if row["left_index"] is not None else {}
    right_values = right["rows"][row["right_index"]] if row["right_index"] is not None else {}
    evidence = dict(row["evidence"])
    if "similarity" in evidence:
        evidence["similarity"] = _confidence(evidence["similarity"])
    return {
        "status": row["status"],
        "key": row["key"] or row["key_left"] or row["key_right"],
        "key_left": row["key_left"],
        "key_right": row["key_right"],
        "confidence": _confidence(row["confidence"]),
        "name_left": row["name_left"],
        "name_right": row["name_right"],
        "left_values": left_values,
        "right_values": right_values,
        "amount_left": row["amount_left"],
        "amount_right": row["amount_right"],
        "amount_delta": row["amount_delta"],
        "amount_delta_ratio": row["amount_delta_ratio"],
        "reason": row["reason"],
        "evidence": evidence,
    }


def _confidence(value) -> str:
    if isinstance(value, Decimal):
        rendered = format(value, "f")
    elif isinstance(value, float):
        rendered = format(Decimal(str(value)), "f")
    else:
        rendered = str(value)
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _raise_if_broken(result: dict) -> None:
    if result.get("error") == "key.missing":
        raise AppError("request.invalid", RECONCILE_KEY_MISSING, 400)
    if not result["validation"]["ok"]:
        raise AppError("output.invalid", RECONCILE_INVALID, 422)


def _check_key_names(names: list[str]) -> None:
    if len(names) > _MAX_KEY_COLUMNS or any(len(name) > _MAX_COLUMN_NAME for name in names):
        raise AppError("request.invalid", REQUEST_INVALID, 400)


def _matches(data: bytes, report: dict) -> bool:
    try:
        read = read_workbook(data, "xlsx", "مغایرت.xlsx")
    except AppError:
        return False
    if [sheet.name for sheet in read.sheets] != SHEET_NAMES:
        return False
    summary = {}
    for row in read.sheets[0].rows[1:]:
        if len(row) >= 2 and row[0].raw:
            summary[row[0].raw] = row[1].raw
    expected = {
        "منطبق": str(report["summary"]["full_match"]),
        "مغایر": str(report["summary"]["value_mismatch"]),
        "فقط فایل اول": str(report["summary"]["only_left"]),
        "فقط فایل دوم": str(report["summary"]["only_right"]),
        "مشکوک": str(report["summary"]["ambiguous"]),
        "ردیف چپ": str(report["validation"]["left_rows"]),
        "ردیف راست": str(report["validation"]["right_rows"]),
    }
    if any(summary.get(label) != value for label, value in expected.items()):
        return False
    by_status = {label: 0 for label in SUMMARY_LABELS.values()}
    for row in report["rows"]:
        by_status[SUMMARY_LABELS[row["status"]]] += 1
    for sheet in read.sheets[1:-1]:
        if max(len(sheet.rows) - 1, 0) != by_status[sheet.name]:
            return False
    return True


def _workspace_lock(workspace_id: str) -> threading.Lock:
    with _GUARD:
        lock = _LOCKS.get(workspace_id)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[workspace_id] = lock
        return lock
