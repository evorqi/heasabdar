from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from hesabdar.db import Database
from hesabdar.errors import AppError
from hesabdar.files.service import FileService
from hesabdar.inspection.build import build_report
from hesabdar.inspection.readers import read_workbook
from hesabdar.messages import INTERNAL


class InspectionService:
    def __init__(self, files: FileService, database: Database) -> None:
        self.files = files
        self.database = database

    def inspect(self, workspace_id: str, file_id: str) -> dict:
        meta = self.files.get_file(workspace_id, file_id)
        version_id = meta["current_version_id"]
        _record, data = self.files.read_version(workspace_id, version_id)
        before = hashlib.sha256(data).hexdigest()
        read = read_workbook(data, meta["format"], meta["original_name"])
        report = build_report(read, file_id, version_id, meta["format"])
        after = hashlib.sha256(self.files.storage.read_bytes(workspace_id, version_id)).hexdigest()
        if after != before:
            raise AppError("internal", INTERNAL, 500)
        data_rows = sum(sheet["data_row_count"] for sheet in report["sheets"])
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.database.transaction() as conn:
            conn.execute(
                "UPDATE versions SET row_count = ?, sheet_count = ? WHERE id = ?",
                (data_rows, report["sheet_count"], version_id),
            )
            conn.execute(
                """
                INSERT INTO inspections (
                    id, workspace_id, file_id, version_id, report_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    workspace_id,
                    file_id,
                    version_id,
                    json.dumps(report, ensure_ascii=False),
                    created_at,
                ),
            )
        return report
