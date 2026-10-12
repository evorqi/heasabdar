from __future__ import annotations

from dataclasses import dataclass

from hesabdar.config import Settings
from hesabdar.db import Database
from hesabdar.files.service import FileService
from hesabdar.files.storage import Storage
from hesabdar.cleaning.service import CleaningService
from hesabdar.inspection.service import InspectionService


@dataclass
class AppContext:
    settings: Settings
    db: Database
    storage: Storage
    service: FileService
    inspection: InspectionService
    cleaning: CleaningService
