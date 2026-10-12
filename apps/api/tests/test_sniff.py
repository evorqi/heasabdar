from __future__ import annotations

import pytest

from hesabdar.errors import AppError
from hesabdar.files.names import validate_display_name
from hesabdar.files.sniff import detect_format
from hesabdar.messages import FILE_CORRUPT_EXCEL
from tests.samples import make_csv, make_xls, make_xlsx

LIMIT = 200 * 1024 * 1024


def test_accepts_real_signatures() -> None:
    assert detect_format("فروش.xlsx", make_xlsx(), LIMIT) == "xlsx"
    assert detect_format("old.XLS", make_xls(), LIMIT) == "xls"
    assert detect_format("گزارش.csv", make_csv(), LIMIT) == "csv"
    assert detect_format("win.csv", "نام,مبلغ\n".encode("cp1256"), LIMIT) == "csv"


def test_rejects_fake_extension_and_binary() -> None:
    secret = "SECRET_CELL_VALUE_9f3a"
    with pytest.raises(AppError) as excel:
        detect_format("fake.xlsx", secret.encode(), LIMIT)
    assert excel.value.code == "file.corrupt"
    assert excel.value.message == FILE_CORRUPT_EXCEL
    assert secret not in excel.value.message

    with pytest.raises(AppError) as csv_zip:
        detect_format("sheet.csv", make_xlsx(), LIMIT)
    assert csv_zip.value.code == "file.corrupt"

    with pytest.raises(AppError) as pdf:
        validate_display_name("scan.pdf")
    assert pdf.value.code == "file.unsupported_type"


def test_rejects_empty_and_oversized_archive() -> None:
    with pytest.raises(AppError) as empty:
        detect_format("empty.csv", b"", LIMIT)
    assert empty.value.code == "file.empty"

    with pytest.raises(AppError) as bomb:
        detect_format("big.xlsx", make_xlsx(), max_uncompressed_bytes=20)
    assert bomb.value.code == "file.unsafe_archive"


def test_display_name_keeps_persian_and_blocks_paths() -> None:
    assert validate_display_name("  گزارش فروش.csv  ") == "گزارش فروش.csv"
    assert validate_display_name("فایل..نهایی.csv") == "فایل..نهایی.csv"
    with pytest.raises(AppError) as traversal:
        validate_display_name("../secret.csv")
    assert traversal.value.code == "file.invalid_name"
    with pytest.raises(AppError):
        validate_display_name("پوشه/فروش.csv")
    with pytest.raises(AppError):
        validate_display_name("bad\nname.csv")
