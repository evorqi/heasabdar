from __future__ import annotations

import re
from decimal import Decimal
from statistics import median

from hesabdar.inspection.classify import (
    IDENTIFIER_ROLES,
    CellView,
    classify_date,
    looks_like_national_id,
    looks_like_phone,
    normalize_header,
    parse_number,
    role_from_header,
)
from hesabdar.inspection.readers import MAX_SCAN_ROWS, RawSheet, WorkbookRead

PREVIEW_ROWS = 200


def build_report(read: WorkbookRead, file_id: str, version_id: str, file_format: str) -> dict:
    findings: list[dict] = []
    unchecked = [dict(item) for item in read.unchecked]
    sheets: list[dict] = []
    for flag in read.workbook_flags:
        findings.append(_structure_finding(flag))
    for sheet in read.sheets:
        sheets.append(_build_sheet(sheet, findings, unchecked))
    if not sheets:
        findings.append(
            {
                "code": "sheet.empty_workbook",
                "severity": "info",
                "sheet": None,
                "address": None,
                "count": 0,
                "message": "این فایل برگه داده‌ای ندارد.",
                "evidence": {},
            }
        )
    return {
        "file_id": file_id,
        "version_id": version_id,
        "format": file_format,
        "sheet_count": len(sheets),
        "sheets": sheets,
        "findings": findings,
        "unchecked": unchecked,
    }


def _build_sheet(sheet: RawSheet, findings: list[dict], unchecked: list[dict]) -> dict:
    header_index, header_status = _header_position(sheet.rows)
    if sheet.truncated:
        unchecked.append(
            {
                "code": "sheet.truncated",
                "count": PREVIEW_ROWS,
                "message": (
                    f"ادامه برگه {sheet.name} بعد از سقف {MAX_SCAN_ROWS} ردیف بررسی نشده است."
                ),
            }
        )
    if not sheet.rows:
        findings.append(
            {
                "code": "sheet.no_data",
                "severity": "info",
                "sheet": sheet.name,
                "address": None,
                "count": 0,
                "message": f"برگه {sheet.name} داده‌ای ندارد.",
                "evidence": {},
            }
        )
        return _sheet_payload(sheet, header_index, header_status, [], [], 0)
    width = len(sheet.rows[0])
    headers = _headers(sheet.rows[header_index] if header_index < len(sheet.rows) else [], width)
    data_rows = sheet.rows[header_index + 1 :]
    if header_status == "hypothesized":
        findings.append(
            {
                "code": "header.uncertain",
                "severity": "hypothesis",
                "sheet": sheet.name,
                "address": None,
                "count": 1,
                "message": f"ردیف عنوان در برگه {sheet.name} با اطمینان تشخیص داده نشد.",
                "evidence": {"header_row_index": header_index},
            }
        )
    columns = []
    preview_columns: list[list[dict]] = [[] for _ in range(min(len(data_rows), PREVIEW_ROWS))]
    for index, name in enumerate(headers):
        column_cells = [row[index] if index < len(row) else CellView(raw=None) for row in data_rows]
        column, preview = _classify_column(sheet.name, index, name, column_cells, findings)
        columns.append(column)
        for row_index, cell in enumerate(preview):
            preview_columns[row_index].append(cell)
    _duplicates(sheet.name, data_rows, findings)
    if sheet.formulas_without_cache:
        unchecked.append(
            {
                "code": "formula.not_evaluated",
                "count": sheet.formulas_without_cache,
                "sheet": sheet.name,
                "message": "نتیجه فرمول ارزیابی نشده است.",
            }
        )
    _error_findings(sheet, findings)
    if sheet.merged_cell_count:
        findings.append(
            {
                "code": "structure.merged_cells",
                "severity": "info",
                "sheet": sheet.name,
                "address": None,
                "count": sheet.merged_cell_count,
                "message": f"در برگه {sheet.name}، {sheet.merged_cell_count} محدوده ادغام‌شده هست.",
                "evidence": {},
            }
        )
    if sheet.encoding_uncertain:
        findings.append(
            {
                "code": "encoding.uncertain",
                "severity": "hypothesis",
                "sheet": sheet.name,
                "address": None,
                "count": 1,
                "message": "رمزگذاری این CSV با اطمینان تشخیص داده نشد. متن را با خروجی مقایسه کنید.",
                "evidence": {},
            }
        )
    return _sheet_payload(
        sheet,
        header_index,
        header_status,
        columns,
        preview_columns,
        len(data_rows),
    )


def _classify_column(sheet: str, index: int, name: str, cells: list[CellView], findings: list[dict]) -> tuple[dict, list[dict]]:
    role = role_from_header(name)
    from_header = role is not None
    nonempty = [cell for cell in cells if cell.raw not in (None, "")]
    if role is None and nonempty and sum(looks_like_national_id(cell.raw or "") for cell in nonempty) / len(nonempty) >= 0.8:
        role = "national_id"
    elif role is None and nonempty and sum(looks_like_phone(cell.raw or "") for cell in nonempty) / len(nonempty) >= 0.8:
        role = "phone"
    identifier = role in IDENTIFIER_ROLES
    parsed_numbers: list[tuple[int, Decimal]] = []
    invalid_dates: list[int] = []
    ambiguous_dates: list[int] = []
    ambiguous_numbers: list[int] = []
    kinds: list[str] = []
    preview: list[dict] = []
    for row_index, cell in enumerate(cells):
        view, kind, number = _view_cell(cell, identifier, role)
        if row_index < PREVIEW_ROWS:
            preview.append(view)
        if cell.raw in (None, ""):
            continue
        kinds.append(kind)
        if number is not None:
            parsed_numbers.append((row_index, number))
        if "date.invalid" in view["warnings"]:
            invalid_dates.append(row_index)
        if "date.ambiguous" in view["warnings"]:
            ambiguous_dates.append(row_index)
        if "number.ambiguous" in view["warnings"]:
            ambiguous_numbers.append(row_index)
    kind, confidence = _dominant_kind(kinds, identifier, from_header)
    if identifier:
        kind = "identifier"
    samples = [cell.raw for cell in nonempty[:5] if cell.raw]
    if not from_header and role == "national_id":
        findings.append(
            _hypothesis(sheet, f"ستون {name} احتمالاً کد ملی است و به‌عنوان شناسه نگه داشته شد.")
        )
    elif not from_header and role == "phone":
        findings.append(
            _hypothesis(sheet, f"ستون {name} احتمالاً شماره تلفن است و به‌عنوان شناسه نگه داشته شد.")
        )
    elif from_header and identifier:
        findings.append(
            {
                "code": "column.identifier",
                "severity": "info",
                "sheet": sheet,
                "address": None,
                "count": len(nonempty),
                "message": f"ستون {name} به‌عنوان شناسه خوانده شد، نه عدد.",
                "evidence": {"role": role},
            }
        )
    empty_count = sum(cell.raw in (None, "") for cell in cells)
    if empty_count and cells:
        findings.append(
            {
                "code": "column.empty_values",
                "severity": "info",
                "sheet": sheet,
                "address": None,
                "count": empty_count,
                "message": f"در ستون {name}، {empty_count} خانه خالی است.",
                "evidence": {},
            }
        )
    if invalid_dates:
        findings.append(
            {
                "code": "date.invalid",
                "severity": "error",
                "sheet": sheet,
                "address": _row_address(index, invalid_dates[0]),
                "count": len(invalid_dates),
                "message": f"در ستون {name}، {len(invalid_dates)} تاریخ نامعتبر است.",
                "evidence": {"rows": [item + 1 for item in invalid_dates[:8]]},
            }
        )
    if ambiguous_dates:
        findings.append(
            {
                "code": "date.ambiguous",
                "severity": "warning",
                "sheet": sheet,
                "address": _row_address(index, ambiguous_dates[0]),
                "count": len(ambiguous_dates),
                "message": f"در ستون {name}، {len(ambiguous_dates)} تاریخ مبهم بدون تبدیل باقی ماند.",
                "evidence": {"rows": [item + 1 for item in ambiguous_dates[:8]]},
            }
        )
    if ambiguous_numbers:
        findings.append(
            {
                "code": "number.ambiguous",
                "severity": "warning",
                "sheet": sheet,
                "address": None,
                "count": len(ambiguous_numbers),
                "message": f"در ستون {name}، {len(ambiguous_numbers)} عدد بیش از یک تفسیر دارد و قطعی نشد.",
                "evidence": {"rows": [item + 1 for item in ambiguous_numbers[:8]]},
            }
        )
    _outlier(sheet, name, parsed_numbers, findings)
    column = {
        "name": name,
        "normalized_name": normalize_header(name),
        "index": index,
        "kind": kind,
        "kind_confidence": round(confidence, 2),
        "role_hints": [role] if role else [],
        "empty_count": empty_count,
        "samples": samples,
    }
    return column, preview


def _view_cell(cell: CellView, identifier: bool, role: str | None) -> tuple[dict, str, Decimal | None]:
    raw = cell.raw
    warnings: list[str] = []
    if raw in (None, ""):
        return {"raw": None, "parsed": None, "warnings": []}, "blank", None
    if cell.error_token:
        warnings.append("excel.error")
    if identifier:
        return {"raw": raw, "parsed": None, "warnings": warnings}, "identifier", None
    if cell.formula and cell.excel_number is None and not cell.error_token:
        return {"raw": raw, "parsed": None, "warnings": warnings}, "text", None
    if cell.excel_number is not None and role != "date":
        kind = "currency" if role == "amount" and _has_currency_unit(raw) else "number"
        return {"raw": raw, "parsed": str(cell.excel_number), "warnings": warnings}, kind, cell.excel_number
    if raw in {"TRUE", "FALSE", "بله", "خیر"}:
        return {"raw": raw, "parsed": raw, "warnings": warnings}, "boolean", None
    iso_date = _iso_date(raw)
    if iso_date and role != "amount":
        return {"raw": raw, "parsed": iso_date, "warnings": warnings}, "date", None
    parsed_date, date_warning = classify_date(raw)
    if date_warning or (parsed_date and role in {None, "date"}):
        if date_warning:
            warnings.append(date_warning)
        if parsed_date or date_warning:
            return {"raw": raw, "parsed": parsed_date, "warnings": warnings}, "date", None
    number, number_warning = parse_number(raw)
    if number_warning:
        warnings.append(number_warning)
        return {"raw": raw, "parsed": None, "warnings": warnings}, "text", None
    if number is not None:
        kind = "currency" if role == "amount" and _has_currency_unit(raw) else "number"
        return {"raw": raw, "parsed": str(number), "warnings": warnings}, kind, number
    return {"raw": raw, "parsed": None, "warnings": warnings}, "text", None


def _dominant_kind(kinds: list[str], identifier: bool, from_header: bool) -> tuple[str, float]:
    if identifier:
        return "identifier", 0.95 if from_header else 0.6
    if not kinds:
        return "unknown", 0.0
    counts: dict[str, int] = {}
    for kind in kinds:
        counts[kind] = counts.get(kind, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    kind, count = ranked[0]
    share = count / len(kinds)
    if len(ranked) > 1 and ranked[1][1] / len(kinds) >= 0.2 and share < 0.8:
        return "mixed", round(share, 2)
    return kind, share


def _outlier(sheet: str, name: str, values: list[tuple[int, Decimal]], findings: list[dict]) -> None:
    if len(values) < 8:
        return
    midpoint = Decimal(str(median([float(item[1]) for item in values])))
    if midpoint <= 0:
        return
    extreme = max(values, key=lambda item: item[1])
    if extreme[1] <= midpoint * 10:
        return
    findings.append(
        {
            "code": "value.outlier",
            "severity": "hypothesis",
            "sheet": sheet,
            "address": None,
            "count": 1,
            "message": f"در ستون {name} یک مقدار نسبت به میانه خیلی دور است. این به‌تنهایی غلط بودن آن مقدار را ثابت نمی‌کند.",
            "evidence": {"row": extreme[0] + 1},
        }
    )


def _duplicates(sheet: str, rows: list[list[CellView]], findings: list[dict]) -> None:
    seen: dict[tuple, int] = {}
    duplicate_rows: list[int] = []
    for index, row in enumerate(rows):
        key = tuple(cell.raw or "" for cell in row)
        if not any(key):
            continue
        if key in seen:
            duplicate_rows.append(index)
        else:
            seen[key] = index
    if duplicate_rows:
        findings.append(
            {
                "code": "row.duplicate",
                "severity": "warning",
                "sheet": sheet,
                "address": None,
                "count": len(duplicate_rows),
                "message": f"{len(duplicate_rows)} ردیف در برگه {sheet} در همه ستون‌ها با ردیف دیگری یکسان است.",
                "evidence": {"rows": [item + 1 for item in duplicate_rows[:8]]},
            }
        )


def _error_findings(sheet: RawSheet, findings: list[dict]) -> None:
    grouped: dict[str, list[str]] = {}
    for row_index, row in enumerate(sheet.rows):
        for column_index, cell in enumerate(row):
            if cell.error_token:
                grouped.setdefault(cell.error_token, []).append(_row_address(column_index, row_index))
    for token, addresses in grouped.items():
        findings.append(
            {
                "code": "excel.error",
                "severity": "error",
                "sheet": sheet.name,
                "address": addresses[0],
                "count": len(addresses),
                "message": (
                    f"در برگه {sheet.name}، {len(addresses)} مورد خطای \u2066{token}\u2069 دیده شد."
                ),
                "evidence": {"addresses": addresses[:8], "token": token},
            }
        )


def _headers(row: list[CellView], width: int) -> list[str]:
    names: list[str] = []
    for index in range(width):
        raw = row[index].raw if index < len(row) else None
        names.append(raw.strip() if raw and raw.strip() else f"ستون {index + 1}")
    return names


def _header_position(rows: list[list[CellView]]) -> tuple[int, str]:
    limit = min(20, len(rows))
    for index in range(limit):
        filled = [cell for cell in rows[index] if cell.raw not in (None, "")]
        if len(filled) < 2:
            continue
        textual = 0
        for cell in filled:
            number, warning = parse_number(cell.raw or "")
            if number is None or warning:
                textual += 1
        if textual >= max(1, int(len(filled) * 0.6)):
            return index, "detected"
    for index, row in enumerate(rows[:limit]):
        if any(cell.raw not in (None, "") for cell in row):
            return index, "hypothesized"
    return 0, "hypothesized"


def _sheet_payload(sheet, header_index, header_status, columns, preview_rows, data_count) -> dict:
    row_count = 0 if not sheet.rows else header_index + 1 + data_count
    return {
        "name": sheet.name,
        "row_count": row_count,
        "column_count": len(columns),
        "data_row_count": data_count,
        "columns": columns,
        "formula_count": sheet.formula_count,
        "error_display_count": sheet.error_display_count,
        "merged_cell_count": sheet.merged_cell_count,
        "unsupported": sheet.unsupported,
        "header_row_index": header_index,
        "header_status": header_status,
        "preview": {
            "row_limit": PREVIEW_ROWS,
            "truncated": data_count > PREVIEW_ROWS or sheet.truncated,
            "rows": preview_rows,
        },
    }


def _structure_finding(flag: str) -> dict:
    messages = {
        "macro": "این فایل ماکرو دارد. بررسی، فایل را بازنویسی نمی‌کند.",
        "pivot_table": "این فایل جدول محوری دارد. بررسی، آن را حذف نمی‌کند.",
        "external_link": "این فایل اتصال خارجی دارد.",
        "chart": "این فایل نمودار دارد.",
        "table": "این فایل جدول اکسل دارد.",
    }
    severity = "warning" if flag in {"macro", "pivot_table", "external_link"} else "info"
    return {
        "code": f"structure.{flag}",
        "severity": severity,
        "sheet": None,
        "address": None,
        "count": 1,
        "message": messages.get(flag, flag),
        "evidence": {"flag": flag},
    }


def _hypothesis(sheet: str, message: str) -> dict:
    return {
        "code": "column.role_hypothesis",
        "severity": "hypothesis",
        "sheet": sheet,
        "address": None,
        "count": 1,
        "message": message,
        "evidence": {},
    }


def _has_currency_unit(raw: str) -> bool:
    return "ریال" in raw or "تومان" in raw


def _iso_date(raw: str) -> str | None:
    matched = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:T\d{2}:\d{2}:\d{2})?", raw)
    if not matched:
        return None
    return matched.group(1)


def _row_address(column: int, row: int) -> str:
    return f"{_column_name(column)}{row + 1}"


def _column_name(index: int) -> str:
    name = ""
    number = index + 1
    while number:
        number, remainder = divmod(number - 1, 26)
        name = chr(65 + remainder) + name
    return name
