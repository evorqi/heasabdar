from __future__ import annotations

import re

from hesabdar.cleaning.rules import clean_cell, neutralize_csv
from hesabdar.inspection.build import build_report
from hesabdar.inspection.readers import WorkbookRead

CONFIRMATION_THRESHOLD = 5


def plan_cleaning(read: WorkbookRead, file_format: str) -> dict:
    structure = build_report(read, "", "", file_format)
    changes: list[dict] = []
    skipped: list[dict] = []
    sheets: list[dict] = []
    sheet_stats: list[dict] = []
    for raw_sheet, summary in zip(read.sheets, structure["sheets"], strict=True):
        _one_sheet(raw_sheet, summary, file_format, changes, skipped, sheets, sheet_stats)
    for flag in read.workbook_flags:
        if flag in {"macro", "pivot_table"}:
            skipped.append(
                {
                    "sheet": None,
                    "row_index": None,
                    "column_index": None,
                    "rule_id": f"structure.{flag}",
                    "message": _structure_note(flag),
                }
            )
    requires = any(
        item["data_rows"] > 0 and item["changed_rows"] * CONFIRMATION_THRESHOLD > item["data_rows"]
        for item in sheet_stats
    )
    reason = None
    if requires:
        reason = (
            "بیش از ۲۰ درصد ردیف‌های یک برگه تغییر می‌کند. "
            "فایل اصلی می‌ماند و نسخه جدید پس از تأیید ساخته می‌شود."
        )
    return {
        "changes": changes,
        "skipped": skipped,
        "stats": {
            "change_count": len(changes),
            "requires_confirmation": requires,
            "confirmation_reason": reason,
            "sheets": sheet_stats,
        },
        "sheets": sheets,
    }


def _one_sheet(raw_sheet, summary, file_format, changes, skipped, sheets, sheet_stats) -> None:
    header_index = summary["header_row_index"]
    columns = summary["columns"]
    grid: list[list[str | None]] = []
    formulas: set[tuple[int, int]] = set()
    changed_data_rows: set[int] = set()
    for row_index, row in enumerate(raw_sheet.rows):
        built: list[str | None] = []
        data_row = row_index > header_index
        row_changed = False
        for column_index, cell in enumerate(row):
            column = columns[column_index] if column_index < len(columns) else None
            kind = column["kind"] if column else "text"
            role = column["role_hints"][0] if column and column["role_hints"] else None
            final, cell_changes, cell_skips = clean_cell(
                cell.raw,
                header=row_index == header_index,
                kind=kind,
                role=role,
                formula=cell.formula,
                error_token=cell.error_token,
            )
            if file_format == "csv" and not cell.formula:
                neutralized = neutralize_csv(final, _parsed(cell_changes, final, kind, role))
                if neutralized != final and final is not None and neutralized is not None:
                    cell_changes.append(("output.neutralize", final, neutralized))
                    final = neutralized
            if cell.formula:
                formulas.add((row_index, column_index))
            for rule_id, before, after in cell_changes:
                changes.append(
                    {
                        "sheet": raw_sheet.name,
                        "row_index": row_index,
                        "column_index": column_index,
                        "before": before,
                        "after": after,
                        "rule_id": rule_id,
                    }
                )
                row_changed = True
            for rule_id, message in cell_skips:
                skipped.append(
                    {
                        "sheet": raw_sheet.name,
                        "row_index": row_index,
                        "column_index": column_index,
                        "rule_id": rule_id,
                        "message": message,
                    }
                )
            built.append(final)
        if row_changed and data_row:
            changed_data_rows.add(row_index)
        grid.append(built)
    if raw_sheet.truncated:
        skipped.append(
            {
                "sheet": raw_sheet.name,
                "row_index": None,
                "column_index": None,
                "rule_id": "sheet.truncated",
                "message": "ادامه برگه بعد از سقف بررسی، در نسخه پاک‌شده نیامده است.",
            }
        )
    sheets.append({"name": raw_sheet.name, "rows": grid, "formulas": formulas})
    sheet_stats.append(
        {
            "name": raw_sheet.name,
            "rows_before": summary["row_count"],
            "rows_after": summary["row_count"],
            "columns_before": summary["column_count"],
            "columns_after": summary["column_count"],
            "data_rows": summary["data_row_count"],
            "changed_rows": len(changed_data_rows),
        }
    )


def _parsed(cell_changes: list[tuple[str, str, str]], final: str | None, kind: str, role: str | None) -> bool:
    if any(item[0] in {"number.parse", "date.parse_jalali", "date.parse_gregorian"} for item in cell_changes):
        return True
    if not final:
        return False
    if kind in {"number", "currency"} or role == "amount":
        return bool(re.fullmatch(r"[+-]?\d+(\.\d+)?( ریال| تومان)?", final))
    if kind == "date" or role == "date":
        return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", final))
    return False


def _structure_note(flag: str) -> str:
    if flag == "macro":
        return "ماکرو در نسخه پاک‌شده کپی نشده است."
    return "جدول محوری در نسخه پاک‌شده کپی نشده است."
