from __future__ import annotations

import csv
import zipfile
from xml.etree import ElementTree as ET
from xml.etree.ElementTree import ParseError
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import PurePath

import xlrd
from charset_normalizer import from_bytes
from openpyxl.utils.cell import coordinate_to_tuple

from hesabdar.errors import AppError
from hesabdar.inspection.classify import ERROR_TOKENS, CellView
from hesabdar.inspection.xlsx_repair import LOAD_ERRORS, open_xlsx
from hesabdar.messages import FILE_CORRUPT_CSV, FILE_CORRUPT_EXCEL, WORKBOOK_PARTIAL

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
    opened = open_xlsx(data)
    if opened is not None:
        formulas, cached, repaired = opened
        sheets: list[RawSheet] | None = None
        try:
            sheets = _collect_sheets(formulas, cached, flags)
        except LOAD_ERRORS:
            sheets = None
        finally:
            _close_book(formulas)
            _close_book(cached)
        if sheets is not None:
            unchecked = [_partial_note()] if repaired else []
            return WorkbookRead(sheets=sheets, workbook_flags=flags, unchecked=unchecked)
    xml_read = _read_xlsx_xml(data, flags)
    if xml_read is None:
        raise AppError("file.corrupt", FILE_CORRUPT_EXCEL, 400)
    return xml_read


def _collect_sheets(formulas, cached, flags: list[str]) -> list[RawSheet]:
    cached_by_name = {sheet.title: sheet for sheet in cached.worksheets} if cached is not None else {}
    sheets = [
        _read_xlsx_sheet(sheet, cached_by_name.get(sheet.title), flags) for sheet in formulas.worksheets
    ]
    if not sheets:
        raise ValueError("empty")
    return sheets


def _close_book(book) -> None:
    if book is None:
        return
    try:
        book.close()
    except OSError:
        return


def _partial_note() -> dict:
    return {"code": "workbook.partial_read", "count": 1, "message": WORKBOOK_PARTIAL}


def _read_xlsx_xml(data: bytes, flags: list[str]) -> WorkbookRead | None:
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile:
        return None
    try:
        names = {info.filename.replace("\\", "/"): info.filename for info in archive.infolist()}
        lower = {key.lower(): key for key in names}
        workbook = _zip_xml(archive, names, lower, "xl/workbook.xml")
        if workbook is None:
            return None
        rels = _zip_xml(archive, names, lower, "xl/_rels/workbook.xml.rels")
        targets = _sheet_targets(rels)
        shared = _shared_strings(archive, names, lower)
        sheets: list[RawSheet] = []
        for name, rel_id in _workbook_sheets(workbook):
            target = targets.get(rel_id or "")
            if not target:
                continue
            sheet_xml = _zip_xml(archive, names, lower, _resolve_xl(target))
            if sheet_xml is None or _local_name(sheet_xml.tag) != "worksheet":
                continue
            sheets.append(_xml_sheet(name, sheet_xml, shared, flags))
        if not sheets:
            return None
        return WorkbookRead(sheets=sheets, workbook_flags=flags, unchecked=[_partial_note()])
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return None
    finally:
        archive.close()


def _zip_xml(archive: zipfile.ZipFile, names: dict[str, str], lower: dict[str, str], path: str):
    key = lower.get(path.lower())
    if key is None:
        return None
    try:
        return ET.fromstring(archive.read(names[key]))
    except (ParseError, KeyError, OSError):
        return None


def _sheet_targets(rels) -> dict[str, str]:
    if rels is None:
        return {}
    targets: dict[str, str] = {}
    for child in rels:
        if _local_name(child.tag) != "Relationship":
            continue
        kind = (child.get("Type") or "").rstrip("/").rsplit("/", 1)[-1].lower()
        if kind != "worksheet":
            continue
        rel_id = child.get("Id")
        target = child.get("Target")
        if rel_id and target:
            targets[rel_id] = target
    return targets


def _workbook_sheets(workbook) -> list[tuple[str, str | None]]:
    found: list[tuple[str, str | None]] = []
    for node in workbook.iter():
        if _local_name(node.tag) != "sheet":
            continue
        rel_id = None
        for attr, value in node.attrib.items():
            if _local_name(attr) == "id":
                rel_id = value
        name = node.get("name") or "sheet"
        found.append((name, rel_id))
    return found


def _resolve_xl(target: str) -> str:
    cleaned = target.replace("\\", "/").lstrip("/")
    if cleaned.lower().startswith("xl/"):
        return cleaned
    return f"xl/{cleaned}"


def _shared_strings(archive: zipfile.ZipFile, names: dict[str, str], lower: dict[str, str]) -> list[str]:
    root = _zip_xml(archive, names, lower, "xl/sharedStrings.xml")
    if root is None:
        return []
    values: list[str] = []
    for node in root:
        if _local_name(node.tag) == "si":
            values.append(_plain_text(node))
    return values


def _plain_text(node) -> str:
    direct = [child for child in node if _local_name(child.tag) == "t"]
    if direct:
        return "".join(child.text or "" for child in direct)
    parts: list[str] = []
    for child in node:
        if _local_name(child.tag) != "r":
            continue
        for nested in child:
            if _local_name(nested.tag) == "t":
                parts.append(nested.text or "")
    return "".join(parts)


def _xml_sheet(name: str, root, shared: list[str], flags: list[str]) -> RawSheet:
    formula_count = 0
    missing_cache = 0
    error_count = 0
    truncated = False
    occupied: dict[int, dict[int, CellView]] = {}
    max_row = 0
    max_col = 0
    sheet_data = next((child for child in root if _local_name(child.tag) == "sheetData"), None)
    next_row = 1
    if sheet_data is not None:
        for row_el in sheet_data:
            if _local_name(row_el.tag) != "row":
                continue
            row_number = _xml_row_number(row_el.get("r"), next_row)
            if row_number is None:
                continue
            next_row = row_number + 1
            if row_number > MAX_SCAN_ROWS:
                truncated = True
                continue
            cells: dict[int, CellView] = {}
            for cell_el in row_el:
                if _local_name(cell_el.tag) != "c":
                    continue
                parsed = _xml_cell(cell_el, shared)
                if parsed is None:
                    continue
                column, view, is_formula, missing, is_error = parsed
                cells[column] = view
                max_col = max(max_col, column)
                formula_count += int(is_formula)
                missing_cache += int(missing)
                error_count += int(is_error)
            occupied[row_number] = cells
            max_row = max(max_row, row_number)
    rows: list[list[CellView]] = []
    for index in range(1, max_row + 1):
        cells = occupied.get(index, {})
        rows.append([cells.get(column, CellView(raw=None)) for column in range(1, max_col + 1)])
    validations = sum(1 for node in root.iter() if _local_name(node.tag) == "dataValidation")
    unsupported = list(flags)
    if validations:
        unsupported.append("data_validation")
    merged = sum(1 for node in root.iter() if _local_name(node.tag) == "mergeCell")
    return RawSheet(
        name=name,
        rows=_trim_rows(rows),
        truncated=truncated,
        formula_count=formula_count,
        formulas_without_cache=missing_cache,
        error_display_count=error_count,
        merged_cell_count=merged,
        unsupported=_unique(unsupported),
    )


def _xml_cell(cell, shared: list[str]):
    ref = cell.get("r")
    if not ref:
        return None
    try:
        _row, column = coordinate_to_tuple(ref)
    except ValueError:
        return None
    if column < 1 or column > 16384:
        return None
    kind = cell.get("t") or "n"
    formula = None
    value = None
    for child in cell:
        local = _local_name(child.tag)
        if local == "f":
            formula = child.text or ""
        elif local == "v":
            value = child.text
        elif local == "is":
            value = _plain_text(child)
            kind = "inlineStr"
    if formula:
        if not formula.startswith("="):
            formula = f"={formula}"
        error = _error_token(value)
        view = CellView(raw=_limit(formula), formula=True, error_token=error)
        return column, view, True, value is None and error is None, error is not None
    if kind == "inlineStr":
        return column, CellView(raw=_limit(value) if value else None), False, False, False
    if kind == "s":
        try:
            text = shared[int(value)]
        except (TypeError, ValueError, IndexError):
            return column, CellView(raw=None), False, False, False
        return column, CellView(raw=_limit(text) if text else None), False, False, False
    if kind == "b":
        return column, CellView(raw="TRUE" if value == "1" else "FALSE"), False, False, False
    if kind == "e":
        token = _error_token(value) or "#N/A"
        return column, CellView(raw=_limit(value or token), error_token=token), False, False, True
    if kind == "d":
        return column, CellView(raw=_limit(value) if value else None), False, False, False
    if value is None:
        return column, CellView(raw=None), False, False, False
    error = _error_token(value)
    if error:
        return column, CellView(raw=error, error_token=error), False, False, True
    number = _xml_number(value)
    if number is not None:
        rendered = _render_number(number)
        return column, CellView(raw=rendered, excel_number=Decimal(rendered)), False, False, False
    return column, CellView(raw=_limit(value)), False, False, False


def _xml_number(value: str):
    try:
        if any(mark in value for mark in (".", "e", "E")):
            number = float(value)
            if number != number or number in (float("inf"), float("-inf")):
                return None
            return number
        return int(value)
    except ValueError:
        return None


def _xml_row_number(value: str | None, fallback: int) -> int | None:
    if value is None:
        return fallback if fallback >= 1 else None
    if not value.isdigit():
        return None
    number = int(value)
    if number < 1:
        return None
    return number


def _local_name(tag: str) -> str:
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


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
    if any(name.startswith("xl/charts/") or name.startswith("xl/chartsheets/") for name in names):
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
