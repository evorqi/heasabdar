from __future__ import annotations

import hashlib
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from hesabdar.db import Database
from hesabdar.errors import AppError
from hesabdar.files.names import safe_echo_name, validate_display_name
from hesabdar.files.sniff import MEDIA_TYPES, detect_format
from hesabdar.files.storage import Storage
from hesabdar.messages import (
    FILE_NOT_FOUND,
    NONE_ACCEPTED,
    TITLE_LONG,
    TITLE_REQUIRED,
    TOO_MANY_FILES,
    VERSION_NOT_FOUND,
    WORKSPACE_NOT_FOUND,
    file_too_large,
)


@dataclass
class StoredFile:
    id: str
    workspace_id: str
    original_name: str
    format: str
    media_type: str
    byte_size: int
    sha256: str
    current_version_id: str
    created_at: str
    status: str = "stored"


@dataclass
class RejectedFile:
    filename: str
    code: str
    message: str


@dataclass
class UploadBatch:
    accepted: list[StoredFile]
    rejected: list[RejectedFile]


class FileService:
    def __init__(
        self,
        db: Database,
        storage: Storage,
        max_uncompressed_bytes: int,
        max_files_per_upload: int,
        max_upload_bytes: int,
    ) -> None:
        self.db = db
        self.storage = storage
        self.max_uncompressed_bytes = max_uncompressed_bytes
        self.max_files_per_upload = max_files_per_upload
        self.max_upload_bytes = max_upload_bytes

    def create_workspace(self, title: str) -> dict:
        cleaned = (title or "").strip()
        if not cleaned or any(ord(char) < 32 for char in cleaned):
            raise AppError("request.invalid", TITLE_REQUIRED, 400)
        if len(cleaned) > 120:
            raise AppError("request.invalid", TITLE_LONG, 400)
        workspace_id = str(uuid.uuid4())
        created_at = _now()
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO workspaces (id, title, created_at) VALUES (?, ?, ?)",
                (workspace_id, cleaned, created_at),
            )
        return {
            "id": workspace_id,
            "title": cleaned,
            "created_at": created_at,
            "file_count": 0,
        }

    def get_workspace(self, workspace_id: str) -> dict:
        _parse_uuid(workspace_id, WORKSPACE_NOT_FOUND)
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
            if row is None:
                raise AppError("workspace.not_found", WORKSPACE_NOT_FOUND, 404)
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM files WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()["n"]
        return {
            "id": row["id"],
            "title": row["title"],
            "created_at": row["created_at"],
            "file_count": count,
        }

    def list_files(self, workspace_id: str) -> list[dict]:
        self.get_workspace(workspace_id)
        with self.db.transaction() as conn:
            rows = conn.execute(
                """
                SELECT * FROM files
                WHERE workspace_id = ?
                ORDER BY created_at DESC, id DESC
                """,
                (workspace_id,),
            ).fetchall()
        return [asdict(_row_to_file(row)) for row in rows]

    def get_file(self, workspace_id: str, file_id: str) -> dict:
        self.get_workspace(workspace_id)
        _parse_uuid(file_id, FILE_NOT_FOUND)
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM files WHERE id = ? AND workspace_id = ?",
                (file_id, workspace_id),
            ).fetchone()
        if row is None:
            raise AppError("file.not_found", FILE_NOT_FOUND, 404)
        return asdict(_row_to_file(row))

    def read_version(self, workspace_id: str, version_id: str) -> tuple[dict, bytes]:
        self.get_workspace(workspace_id)
        _parse_uuid(version_id, VERSION_NOT_FOUND)
        with self.db.transaction() as conn:
            row = conn.execute(
                """
                SELECT f.* FROM versions v
                JOIN files f ON f.id = v.file_id
                WHERE v.id = ? AND f.workspace_id = ?
                """,
                (version_id, workspace_id),
            ).fetchone()
        if row is None:
            raise AppError("version.not_found", VERSION_NOT_FOUND, 404)
        data = self.storage.read_bytes(workspace_id, version_id)
        return asdict(_row_to_file(row)), data

    def store_files(self, workspace_id: str, payloads: list[tuple[str, bytes]]) -> UploadBatch:
        self.get_workspace(workspace_id)
        if len(payloads) > self.max_files_per_upload:
            raise AppError(
                "file.too_many",
                TOO_MANY_FILES.format(limit=self.max_files_per_upload),
                400,
            )
        accepted: list[StoredFile] = []
        rejected: list[RejectedFile] = []
        for raw_name, data in payloads:
            echo = safe_echo_name(raw_name)
            try:
                if len(data) > self.max_upload_bytes:
                    raise AppError("file.too_large", file_too_large(self.max_upload_bytes), 413)
                name = validate_display_name(raw_name)
                kind = detect_format(name, data, self.max_uncompressed_bytes)
                stored = self._persist(workspace_id, name, kind, data)
            except AppError as exc:
                rejected.append(RejectedFile(filename=echo, code=exc.code, message=exc.message))
                continue
            accepted.append(stored)
        return UploadBatch(accepted=accepted, rejected=rejected)

    def _persist(self, workspace_id: str, name: str, kind: str, data: bytes) -> StoredFile:
        file_id = str(uuid.uuid4())
        version_id = str(uuid.uuid4())
        created_at = _now()
        digest = hashlib.sha256(data).hexdigest()
        self.storage.write_original(workspace_id, version_id, data)
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO files (
                        id, workspace_id, original_name, format, media_type,
                        byte_size, sha256, current_version_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)
                    """,
                    (
                        file_id,
                        workspace_id,
                        name,
                        kind,
                        MEDIA_TYPES[kind],
                        len(data),
                        digest,
                        created_at,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO versions (
                        id, file_id, parent_version_id, kind, blob_name, operation_id,
                        sha256, byte_size, row_count, sheet_count, created_at, note
                    ) VALUES (?, ?, NULL, 'original', ?, NULL, ?, ?, NULL, NULL, ?, ?)
                    """,
                    (
                        version_id,
                        file_id,
                        version_id,
                        digest,
                        len(data),
                        created_at,
                        "نسخه اصلی بارگذاری‌شده",
                    ),
                )
                conn.execute(
                    "UPDATE files SET current_version_id = ? WHERE id = ?",
                    (version_id, file_id),
                )
        except Exception:
            self.storage.remove(workspace_id, version_id)
            raise
        return StoredFile(
            id=file_id,
            workspace_id=workspace_id,
            original_name=name,
            format=kind,
            media_type=MEDIA_TYPES[kind],
            byte_size=len(data),
            sha256=digest,
            current_version_id=version_id,
            created_at=created_at,
        )

    def add_derived_version(
        self,
        workspace_id: str,
        file_id: str,
        parent_version_id: str,
        data: bytes,
        *,
        kind: str,
        note: str,
        operation_id: str,
        row_count: int,
        sheet_count: int,
    ) -> str:
        meta = self.get_file(workspace_id, file_id)
        if meta["current_version_id"] != parent_version_id:
            raise AppError("version.not_found", VERSION_NOT_FOUND, 404)
        version_id = str(uuid.uuid4())
        digest = hashlib.sha256(data).hexdigest()
        created_at = _now()
        self.storage.write_original(workspace_id, version_id, data)
        try:
            with self.db.transaction() as conn:
                parent = conn.execute(
                    """
                    SELECT v.id FROM versions v
                    JOIN files f ON f.id = v.file_id
                    WHERE v.id = ? AND f.id = ? AND f.workspace_id = ?
                    """,
                    (parent_version_id, file_id, workspace_id),
                ).fetchone()
                if parent is None:
                    raise AppError("version.not_found", VERSION_NOT_FOUND, 404)
                conn.execute(
                    """
                    INSERT INTO versions (
                        id, file_id, parent_version_id, kind, blob_name, operation_id,
                        sha256, byte_size, row_count, sheet_count, created_at, note
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        version_id,
                        file_id,
                        parent_version_id,
                        kind,
                        version_id,
                        operation_id,
                        digest,
                        len(data),
                        row_count,
                        sheet_count,
                        created_at,
                        note,
                    ),
                )
                conn.execute(
                    """
                    UPDATE files
                    SET current_version_id = ?, byte_size = ?, sha256 = ?
                    WHERE id = ? AND workspace_id = ?
                    """,
                    (version_id, len(data), digest, file_id, workspace_id),
                )
        except Exception:
            self.storage.remove(workspace_id, version_id)
            raise
        return version_id

    def point_at_version(self, workspace_id: str, file_id: str, version_id: str) -> dict:
        self.get_file(workspace_id, file_id)
        _parse_uuid(version_id, VERSION_NOT_FOUND)
        with self.db.transaction() as conn:
            row = conn.execute(
                """
                SELECT v.sha256, v.byte_size FROM versions v
                JOIN files f ON f.id = v.file_id
                WHERE v.id = ? AND f.id = ? AND f.workspace_id = ?
                """,
                (version_id, file_id, workspace_id),
            ).fetchone()
            if row is None:
                raise AppError("version.not_found", VERSION_NOT_FOUND, 404)
            conn.execute(
                """
                UPDATE files
                SET current_version_id = ?, byte_size = ?, sha256 = ?
                WHERE id = ? AND workspace_id = ?
                """,
                (version_id, row["byte_size"], row["sha256"], file_id, workspace_id),
            )
        return self.get_file(workspace_id, file_id)

    def add_output_file(
        self,
        workspace_id: str,
        name: str,
        data: bytes,
        *,
        kind: str,
        note: str,
        parent_version_id: str | None,
        operation_id: str,
        row_count: int,
        sheet_count: int,
    ) -> StoredFile:
        self.get_workspace(workspace_id)
        file_id = str(uuid.uuid4())
        version_id = str(uuid.uuid4())
        digest = hashlib.sha256(data).hexdigest()
        created_at = _now()
        self.storage.write_original(workspace_id, version_id, data)
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO files (
                        id, workspace_id, original_name, format, media_type,
                        byte_size, sha256, current_version_id, created_at
                    ) VALUES (?, ?, ?, 'xlsx', ?, ?, ?, NULL, ?)
                    """,
                    (
                        file_id,
                        workspace_id,
                        name,
                        MEDIA_TYPES["xlsx"],
                        len(data),
                        digest,
                        created_at,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO versions (
                        id, file_id, parent_version_id, kind, blob_name, operation_id,
                        sha256, byte_size, row_count, sheet_count, created_at, note
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        version_id,
                        file_id,
                        parent_version_id,
                        kind,
                        version_id,
                        operation_id,
                        digest,
                        len(data),
                        row_count,
                        sheet_count,
                        created_at,
                        note,
                    ),
                )
                conn.execute(
                    "UPDATE files SET current_version_id = ? WHERE id = ?",
                    (version_id, file_id),
                )
        except Exception:
            self.storage.remove(workspace_id, version_id)
            raise
        return self.get_file(workspace_id, file_id)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_uuid(value: str, message: str) -> None:
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        raise AppError("request.invalid", message, 404) from None


def _row_to_file(row) -> StoredFile:
    return StoredFile(
        id=row["id"],
        workspace_id=row["workspace_id"],
        original_name=row["original_name"],
        format=row["format"],
        media_type=row["media_type"],
        byte_size=row["byte_size"],
        sha256=row["sha256"],
        current_version_id=row["current_version_id"],
        created_at=row["created_at"],
    )


def batch_failure(batch: UploadBatch) -> AppError:
    return AppError(
        "file.rejected",
        NONE_ACCEPTED,
        400,
        detail={"rejected": [asdict(item) for item in batch.rejected]},
    )
