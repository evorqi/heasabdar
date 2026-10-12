from __future__ import annotations

import csv
import zipfile
from xml.etree.ElementTree import ParseError
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import PurePath

import openpyxl
import xlrd
from charset_normalizer import from_bytes
from openpyxl.utils.exceptions import InvalidFileException

from hesabdar.errors import AppError
from hesabdar.inspection.classify import ERROR_TOKENS, CellView
from hesabdar.messages import FILE_CORRUPT_CSV, FILE_CORRUPT_EXCEL

MAX_SCAN_ROWS = 50000
CELL_CHAR_LIMIT = 4000


@dataclass
class RawSheet:
    name: str
    rows: list[list[CellView]]
    truncated: bool = False
    formula_count: int = 0
    formulas_without_cache: int = 0
    error_display_count: int = 0
    merged_cell_count: int = 0
    unsupported: list[str] = field(default_factory=list)
    encoding_uncertain: bool = False


@dataclass
class WorkbookRead:
    sheets: list[RawSheet]
    workbook_flags: list[str]
    unchecked: list[dict]


def read_workbook(data: bytes, file_format: str, filename: str) -> WorkbookRead:
    if file_format == "xlsx":
        return _read_xlsx(data)
    if file_format == "xls":
        return _read_xls(data)
    if file_format == "csv":
        return _read_csv(data, filename)
    raise AppError("file.unsupported_type", FILE_CORRUPT_EXCEL, 400)


def _read_xlsx(data: bytes) -> WorkbookRead:
    flags = _zip_flags(data)
    formulas = None
    cached = None
    try:
        formulas = openpyxl.load_workbook(BytesIO(data), data_only=False, read_only=False)
        cached = openpyxl.load_workbook(BytesIO(data), data_only=True, read_only=False)
    except (
        InvalidFileException,
        zipfile.BadZipFile,
        OSError,
        ValueError,
        KeyError,
        ParseError,
        TypeError,
    ):
        if formulas is not None:
            formulas.close()
        raise AppError("file.corrupt", FILE_CORRUPT_EXCEL, 400) from None
    sheets: list[RawSheet] = []
    try:
        cached_by_name = {sheet.title: sheet for sheet in cached.worksheets}
        for sheet in formulas.worksheets:
            sheets.append(_read_xlsx_sheet(sheet, cached_by_name.get(sheet.title), flags))
    except (InvalidFileException, ValueError, KeyError, ParseError, TypeError):
        raise AppError("file.corrupt", FILE_CORRUPT_EXCEL, 400) from None
    finally:
        formulas.close()
        cached.close()
    return WorkbookRead(sheets=sheets, workbook_flags=flags, unchecked=[])


def _read_xlsx_sheet(sheet, cached, flags: list[str]) -> RawSheet:
    cached_rows = list(cached.iter_rows(values_only=True)) if cached is not None else []
    rows: list[list[CellView]] = []
    formula_count = 0
    missing_cache = 0
    error_count = 0
    truncated = False
    for index, row in enumerate(sheet.iter_rows()):
        if index >= MAX_SCAN_ROWS:
            truncated = True
            break
        cached_row = cached_rows[index] if index < len(cached_rows) else ()
        built: list[CellView] = []
        for column, cell in enumerate(row):
            cached_value = cached_row[column] if column < len(cached_row) else None
            view, is_formula, missing, is_error = _xlsx_cell(cell, cached_value)
            built.append(view)
            formula_count += int(is_formula)
            missing_cache += int(missing)
            error_count += int(is_error)
        rows.append(built)
    unsupported = list(flags)
    merged = len(sheet.merged_cells.ranges)
    validations = sheet.data_validations.dataValidation if sheet.data_validations else []
    if validations:
        unsupported.append("data_validation")
    return RawSheet(
        name=sheet.title,
        rows=_trim_rows(rows),
        truncated=truncated,
        formula_count=formula_count,
        formulas_without_cache=missing_cache,
        error_display_count=error_count,
        merged_cell_count=merged,
        unsupported=_unique(unsupported),
    )


def _xlsx_cell(cell, cached_value) -> tuple[CellView, bool, bool, bool]:
    if cell.value is None and cell.data_type != "f":
        return CellView(raw=None), False, False, False
    if cell.data_type == "f":
        formula = cell.value if isinstance(cell.value, str) else str(cell.value)
        if not str(formula).startswith("="):
            formula = f"={formula}"
        error = _error_token(cached_value)
        cached_missing = cached_value is None
        view = CellView(raw=_limit(str(formula)), formula=True, error_token=error)
        return view, True, cached_missing and error is None, error is not None
    error = _error_token(cell.value)
    if error or cell.data_type == "e":
        token = error or _error_token(str(cell.value))
        return CellView(raw=_limit(str(cell.value)), error_token=token), False, False, token is not None
    if cell.data_type == "n" and isinstance(cell.value, (int, float)):
        rendered = _render_number(cell.value)
        return (
            CellView(raw=rendered, excel_number=Decimal(rendered)),
            False,
            False,
            False,
        )
    if cell.data_type == "d" and isinstance(cell.value, (datetime, date)):
        return CellView(raw=cell.value.isoformat()), False, False, False
    if cell.data_type == "b":
        return CellView(raw="TRUE" if cell.value else "FALSE"), False, False, False
    if isinstance(cell.value, (datetime, date, time)):
        return CellView(raw=cell.value.isoformat()), False, False, False
    return CellView(raw=_limit(str(cell.value))), False, False, False


def _read_xls(data: bytes) -> WorkbookRead:
    try:
        book = xlrd.open_workbook(file_contents=data)
    except xlrd.XLRDError:
        raise AppError("file.corrupt", FILE_CORRUPT_EXCEL, 400) from None
    sheets = [_read_xls_sheet(book.sheet_by_index(index)) for index in range(book.nsheets)]
    unchecked = [
        {
            "code": "formula.text_unavailable",
            "count": 1,
            "message": "متن فرمول‌های فایل xls با این موتور خوانده نمی‌شود. فقط مقدار ذخیره‌شده بررسی شد.",
        }
    ]
    return WorkbookRead(sheets=sheets, workbook_flags=[], unchecked=unchecked)


def _read_xls_sheet(sheet) -> RawSheet:
    error_map = {
        0: "#NULL!",
        7: "#DIV/0!",
        15: "#VALUE!",
        23: "#REF!",
        29: "#NAME?",
        36: "#NUM!",
        42: "#N/A",
    }
    rows: list[list[CellView]] = []
    error_count = 0
    truncated = False
    last = min(sheet.nrows, MAX_SCAN_ROWS)
    truncated = sheet.nrows > MAX_SCAN_ROWS
    for row_index in range(last):
        built: list[CellView] = []
        for column in range(sheet.ncols):
            kind = sheet.cell_type(row_index, column)
            value = sheet.cell_value(row_index, column)
            if kind in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                built.append(CellView(raw=None))
            elif kind == xlrd.XL_CELL_TEXT:
                built.append(CellView(raw=_limit(str(value))))
            elif kind == xlrd.XL_CELL_NUMBER:
                rendered = _render_number(value)
                built.append(CellView(raw=rendered, excel_number=Decimal(rendered)))
            elif kind == xlrd.XL_CELL_DATE:
                try:
                    rendered = xlrd.xldate_as_datetime(value, sheet.book.datemode).isoformat()
                except (ValueError, xlrd.xldate.XLDateError):
                    rendered = str(value)
                built.append(CellView(raw=rendered))
            elif kind == xlrd.XL_CELL_BOOLEAN:
                built.append(CellView(raw="TRUE" if value else "FALSE"))
            elif kind == xlrd.XL_CELL_ERROR:
                token = error_map.get(int(value), "#N/A")
                error_count += 1
                built.append(CellView(raw=token, error_token=token))
            else:
                built.append(CellView(raw=_limit(str(value)) if value != "" else None))
        rows.append(built)
    return RawSheet(
        name=sheet.name,
        rows=_trim_rows(rows),
        truncated=truncated,
        error_display_count=error_count,
    )


def _read_csv(data: bytes, filename: str) -> WorkbookRead:
    text, uncertain = _decode_csv(data)
    if text is None:
        raise AppError("file.corrupt", FILE_CORRUPT_CSV, 400)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    dialect.quotechar = '"'
    dialect.doublequote = True
    reader = csv.reader(StringIO(text), dialect)
    rows: list[list[CellView]] = []
    truncated = False
    for index, row in enumerate(reader):
        if index >= MAX_SCAN_ROWS:
            truncated = True
            break
        rows.append([CellView(raw=_limit(cell) if cell != "" else None) for cell in row])
    stem = PurePath(filename).stem or "csv"
    sheet = RawSheet(name=stem, rows=_trim_rows(rows), truncated=truncated, encoding_uncertain=uncertain)
    return WorkbookRead(sheets=[sheet], workbook_flags=[], unchecked=[])


def _decode_csv(data: bytes) -> tuple[str | None, bool]:
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        try:
            return data.decode("utf-16"), False
        except UnicodeDecodeError:
            return None, False
    try:
        return data.decode("utf-8-sig"), False
    except UnicodeDecodeError:
        pass
    guessed = from_bytes(data).best()
    if guessed is None:
        return None, False
    uncertain = guessed.coherence < 0.7
    try:
        return str(guessed), uncertain
    except Exception:
        return None, False


def _zip_flags(data: bytes) -> list[str]:
    labels: list[str] = []
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            names = [info.filename.replace("\\", "/").lower() for info in archive.infolist()]
    except zipfile.BadZipFile:
        raise AppError("file.corrupt", FILE_CORRUPT_EXCEL, 400) from None
    if any(name.endswith("vbaproject.bin") for name in names):
        labels.append("macro")
    if any("pivotcache" in name or "pivottable" in name for name in names):
        labels.append("pivot_table")
    if any(name.startswith("xl/externallinks/") for name in names):
        labels.append("external_link")
    if any(name.startswith("xl/charts/") for name in names):
        labels.append("chart")
    if any(name.startswith("xl/tables/") for name in names):
        labels.append("table")
    return labels


def _trim_rows(rows: list[list[CellView]]) -> list[list[CellView]]:
    while rows and not any(cell.raw not in (None, "") for cell in rows[-1]):
        rows.pop()
    width = 0
    for row in rows:
        for index, cell in enumerate(row, start=1):
            if cell.raw not in (None, ""):
                width = max(width, index)
    if width == 0:
        return []
    trimmed: list[list[CellView]] = []
    for row in rows:
        short = row[:width]
        if len(short) < width:
            short = short + [CellView(raw=None) for _ in range(width - len(short))]
        trimmed.append(short)
    return trimmed


def _render_number(value: float | int) -> str:
    if isinstance(value, int) or (isinstance(value, float) and float(value).is_integer()):
        return str(int(value))
    rendered = format(Decimal(str(value)), "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def _error_token(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    for token in ERROR_TOKENS:
        if text == token:
            return token
    return None


def _limit(value: str) -> str:
    if len(value) <= CELL_CHAR_LIMIT:
        return value
    return value[:CELL_CHAR_LIMIT]


def _unique(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen
