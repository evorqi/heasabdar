from __future__ import annotations

import os
import time
import uuid

import pytest

from hesabdar.errors import AppError
from hesabdar.files.storage import Storage


def test_blob_path_is_generated_and_exclusive(tmp_path) -> None:
    storage = Storage(tmp_path / "data")
    workspace_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())
    storage.write_original(workspace_id, version_id, "علی‌رضا".encode())
    blob = tmp_path / "data" / "blobs" / workspace_id / version_id
    assert blob.read_bytes() == "علی‌رضا".encode()
    assert "علی" not in blob.name
    with pytest.raises(FileExistsError):
        storage.write_original(workspace_id, version_id, b"other")
    with pytest.raises(AppError):
        storage.write_original("../evil", version_id, b"nope")
    assert not (tmp_path / "evil").exists()


def test_old_tmp_files_are_removed(tmp_path) -> None:
    storage = Storage(tmp_path / "data", tmp_max_age_seconds=24 * 60 * 60)
    stale = storage.tmp_root / str(uuid.uuid4())
    fresh = storage.tmp_root / str(uuid.uuid4())
    stale.write_bytes(b"old")
    fresh.write_bytes(b"new")
    old_time = time.time() - (25 * 60 * 60)
    os.utime(stale, (old_time, old_time))
    removed = storage.cleanup_old_tmp()
    assert removed == 1
    assert not stale.exists()
    assert fresh.read_bytes() == b"new"
