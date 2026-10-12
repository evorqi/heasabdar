from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

from hesabdar.errors import AppError
from hesabdar.messages import INTERNAL

_UUID = uuid.UUID


class Storage:
    def __init__(self, data_dir: Path, tmp_max_age_seconds: int = 24 * 60 * 60) -> None:
        self.data_dir = data_dir.resolve()
        self.tmp_max_age_seconds = tmp_max_age_seconds
        self.blob_root = self.data_dir / "blobs"
        self.tmp_root = self.data_dir / "tmp"
        self.blob_root.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.tmp_root.mkdir(parents=True, mode=0o700, exist_ok=True)

    def write_original(self, workspace_id: str, version_id: str, data: bytes) -> str:
        workspace_id = _require_uuid(workspace_id)
        version_id = _require_uuid(version_id)
        destination = self._blob_path(workspace_id, version_id)
        if destination.exists():
            raise FileExistsError(version_id)
        destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        temporary = self.tmp_root / str(uuid.uuid4())
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        if destination.exists():
            temporary.unlink(missing_ok=True)
            raise FileExistsError(version_id)
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
        return version_id

    def read_bytes(self, workspace_id: str, version_id: str) -> bytes:
        path = self._blob_path(_require_uuid(workspace_id), _require_uuid(version_id))
        if not path.is_file():
            raise AppError("version.not_found", INTERNAL, 404)
        return path.read_bytes()

    def remove(self, workspace_id: str, version_id: str) -> None:
        path = self._blob_path(_require_uuid(workspace_id), _require_uuid(version_id))
        if path.is_file():
            path.unlink()

    def cleanup_old_tmp(self, now: float | None = None) -> int:
        moment = time.time() if now is None else now
        removed = 0
        if not self.tmp_root.exists():
            return 0
        for entry in self.tmp_root.iterdir():
            if not entry.is_file():
                continue
            age = moment - entry.stat().st_mtime
            if age >= self.tmp_max_age_seconds:
                entry.unlink()
                removed += 1
        return removed

    def _blob_path(self, workspace_id: str, version_id: str) -> Path:
        path = (self.blob_root / workspace_id / version_id).resolve()
        root = self.blob_root.resolve()
        if path.parent.parent != root or path.parent.name != workspace_id:
            raise AppError("file.invalid_name", INTERNAL, 400)
        return path


def _require_uuid(value: str) -> str:
    try:
        parsed = _UUID(value)
    except (ValueError, AttributeError, TypeError):
        raise AppError("request.invalid", INTERNAL, 400) from None
    return str(parsed)
