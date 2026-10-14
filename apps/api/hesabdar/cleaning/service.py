from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone

from hesabdar.cleaning.plan import plan_cleaning
from hesabdar.db import Database
from hesabdar.errors import AppError
from hesabdar.files.service import FileService
from hesabdar.files.workbook import write_workbook
from hesabdar.inspection.readers import read_workbook
from hesabdar.validation.limits import assert_complete
from hesabdar.messages import CLEAN_SUCCEEDED, CLEAN_UNCHANGED, CLEAN_WAITING, OUTPUT_INVALID

_GUARD = threading.Lock()
_LOCKS: dict[str, threading.Lock] = {}


class CleaningService:
    def __init__(self, files: FileService, database: Database) -> None:
        self.files = files
        self.database = database

    def preview(self, workspace_id: str, file_id: str) -> dict:
        meta, _data, plan = self._plan(workspace_id, file_id)
        return _public(meta, plan, status="preview", result_version_id=None, message=_preview_message(plan))

    def apply(self, workspace_id: str, file_id: str, confirm: bool) -> dict:
        with _workspace_lock(workspace_id):
            meta, _data, plan = self._plan(workspace_id, file_id)
            if plan["stats"]["change_count"] == 0:
                return _public(meta, plan, status="unchanged", result_version_id=None, message=CLEAN_UNCHANGED)
            if plan["stats"]["requires_confirmation"] and not confirm:
                report = _public(
                    meta,
                    plan,
                    status="waiting_confirmation",
                    result_version_id=None,
                    message=CLEAN_WAITING,
                )
                self._store(workspace_id, file_id, report, None)
                return report
            data = write_workbook(plan["sheets"], meta["format"])
            if not _matches(data, meta, plan["sheets"]):
                raise AppError("output.invalid", OUTPUT_INVALID, 422)
            operation_id = str(uuid.uuid4())
            version_id = self.files.add_derived_version(
                workspace_id,
                file_id,
                meta["current_version_id"],
                data,
                kind="cleaned",
                note="نسخه پاک‌سازی‌شده",
                operation_id=operation_id,
                row_count=sum(item["data_rows"] for item in plan["stats"]["sheets"]),
                sheet_count=len(plan["stats"]["sheets"]),
            )
            report = _public(
                meta,
                plan,
                status="succeeded",
                result_version_id=version_id,
                message=CLEAN_SUCCEEDED,
            )
            self._store(workspace_id, file_id, report, operation_id)
            return report

    def restore(self, workspace_id: str, file_id: str, version_id: str) -> dict:
        with _workspace_lock(workspace_id):
            return self.files.point_at_version(workspace_id, file_id, version_id)

    def _plan(self, workspace_id: str, file_id: str):
        meta = self.files.get_file(workspace_id, file_id)
        _record, data = self.files.read_version(workspace_id, meta["current_version_id"])
        read = read_workbook(data, meta["format"], meta["original_name"])
        assert_complete(read)
        plan = plan_cleaning(read, meta["format"])
        if plan["stats"]["change_count"] != len(plan["changes"]):
            raise AppError("output.invalid", OUTPUT_INVALID, 422)
        return meta, data, plan

    def _store(self, workspace_id: str, file_id: str, report: dict, operation_id: str | None) -> None:
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
                INSERT INTO cleanings (
                    id, workspace_id, file_id, source_version_id, result_version_id,
                    status, report_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    workspace_id,
                    file_id,
                    report["source_version_id"],
                    report["result_version_id"],
                    report["status"],
                    json.dumps(report, ensure_ascii=False),
                    created_at,
                ),
            )


def _public(meta: dict, plan: dict, *, status: str, result_version_id: str | None, message: str) -> dict:
    return {
        "status": status,
        "file_id": meta["id"],
        "source_version_id": meta["current_version_id"],
        "result_version_id": result_version_id,
        "message": message,
        "changes": plan["changes"],
        "skipped": plan["skipped"],
        "stats": plan["stats"],
    }


def _preview_message(plan: dict) -> str:
    count = plan["stats"]["change_count"]
    if count == 0:
        return CLEAN_UNCHANGED
    if plan["stats"]["requires_confirmation"]:
        return plan["stats"]["confirmation_reason"] or CLEAN_WAITING
    return f"{count} تغییر آماده است. فایل اصلی دست نخورده می‌ماند."


def _matches(data: bytes, meta: dict, sheets: list[dict]) -> bool:
    try:
        read = read_workbook(data, meta["format"], meta["original_name"])
    except AppError:
        return False
    if len(read.sheets) != len(sheets):
        return False
    for raw, expected in zip(read.sheets, sheets, strict=True):
        if raw.name != expected["name"]:
            return False
        if len(raw.rows) != len(expected["rows"]):
            return False
        for raw_row, expected_row in zip(raw.rows, expected["rows"], strict=True):
            if len(raw_row) != len(expected_row):
                return False
            for cell, value in zip(raw_row, expected_row, strict=True):
                if (cell.raw or None) != (value or None):
                    return False
    return True


def _workspace_lock(workspace_id: str) -> threading.Lock:
    with _GUARD:
        lock = _LOCKS.get(workspace_id)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[workspace_id] = lock
        return lock
