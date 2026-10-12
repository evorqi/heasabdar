from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from hesabdar.errors import UnsafeBind
from hesabdar.messages import UNSAFE_BIND

DEFAULT_MAX_UPLOAD_BYTES = 30 * 1024 * 1024
DEFAULT_MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
DEFAULT_MAX_FILES = 20
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    host: str = "127.0.0.1"
    port: int = 8000
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES
    max_files_per_upload: int = DEFAULT_MAX_FILES
    access_token: str | None = None
    cors_origins: tuple[str, ...] = (
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    )
    tmp_max_age_seconds: int = 24 * 60 * 60

    @classmethod
    def from_env(cls) -> Settings:
        token = os.environ.get("HESABDAR_ACCESS_TOKEN", "").strip() or None
        origins = os.environ.get("HESABDAR_CORS_ORIGINS", "").strip()
        cors = tuple(part.strip() for part in origins.split(",") if part.strip()) or (
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        )
        return cls(
            data_dir=Path(os.environ.get("HESABDAR_DATA_DIR", "./data")),
            host=os.environ.get("HESABDAR_HOST", "127.0.0.1").strip() or "127.0.0.1",
            port=_positive_int(os.environ.get("HESABDAR_PORT", "8000"), 8000),
            max_upload_bytes=_positive_int(
                os.environ.get("HESABDAR_MAX_UPLOAD_BYTES", ""),
                DEFAULT_MAX_UPLOAD_BYTES,
            ),
            max_uncompressed_bytes=_positive_int(
                os.environ.get("HESABDAR_MAX_UNCOMPRESSED_BYTES", ""),
                DEFAULT_MAX_UNCOMPRESSED_BYTES,
            ),
            max_files_per_upload=_positive_int(
                os.environ.get("HESABDAR_MAX_FILES_PER_UPLOAD", ""),
                DEFAULT_MAX_FILES,
            ),
            access_token=token,
            cors_origins=cors,
        )


def ensure_network_is_locked(settings: Settings) -> None:
    host = settings.host.strip().lower()
    if host in LOOPBACK_HOSTS:
        return
    if settings.access_token:
        return
    raise UnsafeBind(UNSAFE_BIND)


def _positive_int(raw: str, default: int) -> int:
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value < 1:
        return default
    return value
