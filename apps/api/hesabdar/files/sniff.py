from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import PurePath

from hesabdar.errors import AppError
from hesabdar.messages import (
    FILE_CORRUPT_CSV,
    FILE_CORRUPT_EXCEL,
    FILE_EMPTY,
    FILE_UNSAFE_ARCHIVE,
    FILE_UNSUPPORTED,
)

OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")
ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
WORKBOOK_MARKS = ("Workbook".encode("utf-16le"), "Book".encode("utf-16le"))
MAX_ZIP_ENTRIES = 4096
MEDIA_TYPES = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel",
    "csv": "text/csv; charset=utf-8",
}


def detect_format(filename: str, data: bytes, max_uncompressed_bytes: int) -> str:
    if not data:
        raise AppError("file.empty", FILE_EMPTY, 400)
    extension = PurePath(filename).suffix.lower()
    if extension == ".xlsx":
        _validate_xlsx(data, max_uncompressed_bytes)
        return "xlsx"
    if extension == ".xls":
        _validate_xls(data)
        return "xls"
    if extension == ".csv":
        _validate_csv(data)
        return "csv"
    raise AppError("file.unsupported_type", FILE_UNSUPPORTED, 400)


def _validate_xlsx(data: bytes, max_uncompressed_bytes: int) -> None:
    if not data.startswith(ZIP_MAGICS):
        raise AppError("file.corrupt", FILE_CORRUPT_EXCEL, 400)
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                raise AppError("file.unsafe_archive", FILE_UNSAFE_ARCHIVE, 400)
            total = 0
            names: set[str] = set()
            for info in infos:
                if info.flag_bits & 0x1:
                    raise AppError("file.corrupt", FILE_CORRUPT_EXCEL, 400)
                total += max(info.file_size, 0)
                if total > max_uncompressed_bytes:
                    raise AppError("file.unsafe_archive", FILE_UNSAFE_ARCHIVE, 400)
                names.add(info.filename.replace("\\", "/").lower())
            if "[content_types].xml" not in names or "xl/workbook.xml" not in names:
                raise AppError("file.corrupt", FILE_CORRUPT_EXCEL, 400)
    except AppError:
        raise
    except (zipfile.BadZipFile, OSError, ValueError):
        raise AppError("file.corrupt", FILE_CORRUPT_EXCEL, 400) from None


def _validate_xls(data: bytes) -> None:
    if not data.startswith(OLE_MAGIC):
        raise AppError("file.corrupt", FILE_CORRUPT_EXCEL, 400)
    if not any(mark in data for mark in WORKBOOK_MARKS):
        raise AppError("file.corrupt", FILE_CORRUPT_EXCEL, 400)


def _validate_csv(data: bytes) -> None:
    if data.startswith(ZIP_MAGICS) or data.startswith(OLE_MAGIC):
        raise AppError("file.corrupt", FILE_CORRUPT_CSV, 400)
    if data.startswith(b"%PDF") or data.startswith(b"\x89PNG") or data.startswith(b"\xff\xd8\xff"):
        raise AppError("file.corrupt", FILE_CORRUPT_CSV, 400)
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        try:
            data.decode("utf-16")
        except UnicodeDecodeError:
            raise AppError("file.corrupt", FILE_CORRUPT_CSV, 400) from None
        return
    sample = data[:8192]
    if b"\x00" in sample:
        raise AppError("file.corrupt", FILE_CORRUPT_CSV, 400)
    controls = sum(1 for byte in sample if byte < 32 and byte not in (9, 10, 13))
    if controls / len(sample) > 0.02:
        raise AppError("file.corrupt", FILE_CORRUPT_CSV, 400)
    try:
        data.decode("utf-8")
        return
    except UnicodeDecodeError:
        pass
    try:
        data.decode("cp1256")
    except UnicodeDecodeError:
        raise AppError("file.corrupt", FILE_CORRUPT_CSV, 400) from None
