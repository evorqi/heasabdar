from __future__ import annotations

import zipfile
from io import BytesIO

import xlwt
from openpyxl import Workbook

ERROR_TOKENS = ("#REF!", "#VALUE!", "#N/A", "#DIV/0!", "#NAME?", "#NULL!", "#NUM!")


def sales_workbook() -> bytes:
    book = Workbook()
    sales = book.active
    sales.title = "فروش"
    sales.append(["نام", "کد ملی", "مبلغ", "تاریخ", "محاسبه"])
    sales.append(["سارا احمدی", "0012345678", 1500000, "1403/07/20", "=C2*2"])
    sales.append(["رضا", "0123456789", 2500, "1403/13/01", "#DIV/0!"])
    sales["E3"].data_type = "e"
    sales["B2"].number_format = "@"
    sales["B3"].number_format = "@"

    costs = book.create_sheet("هزینه‌ها")
    costs.append(["شرح", "مبلغ"])
    costs.append(["اجاره", 900000])

    book.create_sheet("خالی")
    return _save(book)


def error_workbook() -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "خطاها"
    sheet.append(["پیام"])
    for token in ERROR_TOKENS:
        sheet.append([token])
        sheet.cell(sheet.max_row, 1).data_type = "e"
    sheet["B2"] = "=A2+1"
    return _save(book)


def flagged_workbook() -> bytes:
    base = sales_workbook()
    return _add_zip_entries(
        base,
        {
            "xl/vbaProject.bin": b"not-a-macro",
            "xl/pivotTables/pivotTable1.xml": b"<pivot/>",
        },
    )


def persian_csv() -> bytes:
    return "نام,کد ملی,مبلغ\nعلی‌رضا,۰۰۱۲۳۴۵۶۷۸,۱۲۳۴\n".encode("utf-8-sig")


def persian_xls() -> bytes:
    book = xlwt.Workbook(encoding="utf-8")
    sheet = book.add_sheet("فروش")
    sheet.write(0, 0, "نام")
    sheet.write(0, 1, "کد ملی")
    sheet.write(0, 2, "مبلغ")
    sheet.write(1, 0, "سارا")
    sheet.write(1, 1, "0012345678")
    sheet.write(1, 2, 1500)
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _save(book: Workbook) -> bytes:
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _add_zip_entries(data: bytes, entries: dict[str, bytes]) -> bytes:
    source = zipfile.ZipFile(BytesIO(data))
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for info in source.infolist():
            archive.writestr(info, source.read(info.filename))
        for name, payload in entries.items():
            archive.writestr(name, payload)
    source.close()
    return buffer.getvalue()
