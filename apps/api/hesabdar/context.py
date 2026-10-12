from __future__ import annotations

from dataclasses import dataclass

from hesabdar.config import Settings
from hesabdar.db import Database
from hesabdar.files.service import FileService
from hesabdar.files.storage import Storage


@dataclass
class AppContext:
    settings: Settings
    db: Database
    storage: Storage
    service: FileService
