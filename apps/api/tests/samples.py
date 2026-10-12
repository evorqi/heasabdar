from __future__ import annotations

import zipfile
from io import BytesIO

import xlwt


def make_xlsx(extra_name: str | None = None, extra_payload: bytes = b"") -> bytes:
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        "</Types>"
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheets><sheet name=\"فروش\"/></sheets></workbook>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("xl/workbook.xml", workbook)
        if extra_name is not None:
            archive.writestr(extra_name, extra_payload)
    return buffer.getvalue()


def make_xls() -> bytes:
    book = xlwt.Workbook(encoding="utf-8")
    sheet = book.add_sheet("sales")
    sheet.write(0, 0, "نام")
    sheet.write(0, 1, "00123")
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def make_csv() -> bytes:
    return "نام,مبلغ\nعلی‌رضا,۱۲۳\n".encode("utf-8-sig")
