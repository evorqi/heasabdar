from __future__ import annotations

import re

from hesabdar.messages import (
    PLAN_HEADERS,
    PLAN_NEED_HEADER,
    PLAN_NEED_NAME,
    PLAN_NEED_SHEET,
    PLAN_NEED_TWO_SHEETS,
    PLAN_NO_CITY,
    PLAN_NO_GROUP,
    PLAN_NO_ROW,
    PLAN_NO_SPLIT,
    PLAN_ONE_COLUMN,
    PLAN_ONE_SHEET,
    PLAN_SHEET_EXISTS,
)
from hesabdar.planner.explain import render

_SHEET_ORDER = ("فروش", "مشتریان", "محصولات", "گزارش", "داشبورد")
_IDENTIFIER_HEADERS = ("شماره فاکتور", "شناسه مشتری", "کد محصول")
_CITIES = ("تهران", "شیراز", "مشهد")
_DANGER_START = ("=", "+", "-", "@")
_BIDI = frozenset("\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")
_CELL_REF = re.compile(r"(\$?[A-Za-z]{1,3})(\$?\d+)")
_UNSAFE_NAME = set(":\\/?*[]")


def block_reason(flags: list[str], confirmed: bool) -> str | None:
    if confirmed:
        return None
    if "macro" in flags:
        return "macro"
    if "pivot_table" in flags:
        return "pivot"
    return None


def build_management(text: str) -> dict:
    names = [name for name in _SHEET_ORDER if name in text]
    if not names:
        return _ask(PLAN_NEED_NAME)
    sheets = [_template(name) for name in names]
    metrics = {"sheet_count": str(len(sheets))}
    summary = render("فایل با {sheet_count} برگه ساخته شد.", metrics)
    summary = f"{summary} {'، '.join(names)}"
    return {"sheets": sheets, "summary": summary, "warnings": [], "metrics": metrics}


def apply(tool: str, sheets: list[dict], text: str) -> dict:
    if tool == "sheet_merge":
        return merge_tables(sheets, "برگه")
    if tool == "sheet_split":
        return _split(sheets, files=False)
    if tool == "file_split":
        return _split(sheets, files=True)
    if tool == "sheet_add":
        return _add_sheet(sheets, text)
    if tool == "sheet_delete":
        return _delete_sheet(sheets, text)
    if tool == "sheet_rename":
        return _rename_sheet(sheets, text)
    if tool == "sheet_move":
        return _move_sheet(sheets, text)
    if tool == "column_add":
        return _add_column(sheets)
    if tool == "column_delete":
        return _delete_column(sheets, text)
    if tool == "column_move":
        return _move_column(sheets, text)
    if tool == "row_add":
        return _add_row(sheets)
    if tool == "row_delete":
        return _delete_row(sheets)
    if tool == "format_cells":
        return _format(sheets, text)
    if tool == "freeze":
        return _freeze(sheets)
    if tool == "data_validation":
        return _validate(sheets)
    if tool == "export":
        return _export(sheets)
    return _ask(PLAN_NEED_NAME)


def merge_tables(sheets: list[dict], source_label: str) -> dict:
    usable = [sheet for sheet in sheets if sheet.get("rows")]
    if len(usable) < 2:
        return _ask(PLAN_NEED_TWO_SHEETS)
    header = list(usable[0]["rows"][0])
    for sheet in usable[1:]:
        if not _same_header(header, sheet["rows"][0]):
            return _ask(PLAN_HEADERS)
    body: list[list] = []
    mismatch = 0
    for sheet in usable:
        mismatch += _mismatch_count(sheet)
        for row in sheet["rows"][1:]:
            padded = list(row) + [None] * max(len(header) - len(row), 0)
            body.append(padded[: len(header)])
    metrics = {
        "merged_rows": str(len(body)),
        "sheet_count": str(len(usable)),
        "mismatch_count": str(mismatch),
    }
    warnings = []
    if mismatch:
        warnings.append(render("{mismatch_count} فرمول با الگوی ستون یکی نیست.", metrics))
    summary = render(
        "{merged_rows} ردیف داده از {sheet_count} " + source_label + " در یک برگه جمع شد.",
        metrics,
    )
    return {
        "sheets": [
            {
                "name": "ادغام",
                "rows": [header, *body],
                "formulas": set(),
                "bold_header": True,
                "freeze": "A2",
                "text_columns": _text_columns(header),
            }
        ],
        "summary": summary,
        "warnings": warnings,
        "metrics": metrics,
    }


def neutralize_rows(rows: list[list]) -> tuple[list[list], int]:
    changed = 0
    body = []
    for row in rows:
        built = []
        for value in row:
            safe, hit = _neutralize(value)
            changed += int(hit)
            built.append(safe)
        body.append(built)
    return body, changed


def _template(name: str) -> dict:
    if name == "فروش":
        header = ["شماره فاکتور", "تاریخ", "مشتری", "محصول", "شهر", "مبلغ"]
        rows = [header]
        validation = {"values": list(_CITIES), "sqref": "E2:E200"}
    elif name == "مشتریان":
        header = ["شناسه مشتری", "نام", "شهر", "تلفن"]
        rows = [header]
        validation = None
    elif name == "محصولات":
        header = ["کد محصول", "نام", "قیمت"]
        rows = [header]
        validation = None
    elif name == "داشبورد":
        header = ["موضوع", "وضعیت"]
        rows = [header, ["نمودار", "تا وارد شدن داده فروش ساخته نمی‌شود"]]
        validation = None
    else:
        header = ["شاخص", "مقدار", "واحد"]
        rows = [header]
        validation = None
    sheet = {
        "name": name,
        "rows": rows,
        "formulas": set(),
        "bold_header": True,
        "freeze": "A2",
        "text_columns": _text_columns(header),
    }
    if validation:
        sheet["validation"] = validation
    return sheet


def _split(sheets: list[dict], files: bool) -> dict:
    sheet = _main(sheets)
    rows = sheet["rows"]
    if len(rows) < 3:
        return _ask(PLAN_NO_SPLIT)
    data = rows[1:]
    mid = len(data) // 2
    first_rows = [list(rows[0]), *[list(row) for row in data[:mid]]]
    second_rows = [list(rows[0]), *[list(row) for row in data[mid:]]]
    metrics = {"first_rows": str(len(first_rows) - 1), "second_rows": str(len(second_rows) - 1)}
    summary = render("{first_rows} ردیف در بخش اول و {second_rows} ردیف در بخش دوم است.", metrics)
    first = {"name": "بخش ۱", "rows": first_rows, "formulas": set(), "bold_header": True, "text_columns": _text_columns(rows[0])}
    second = {"name": "بخش ۲", "rows": second_rows, "formulas": set(), "bold_header": True, "text_columns": _text_columns(rows[0])}
    if files:
        return {
            "files": [{"name": "بخش ۱.xlsx", "sheets": [first]}, {"name": "بخش ۲.xlsx", "sheets": [second]}],
            "summary": summary,
            "warnings": _formula_warnings(sheet),
            "metrics": {**metrics, "formula_count": str(len(sheet.get("formulas") or []))},
        }
    return {
        "sheets": [first, {**second, "name": "بخش ۲"}],
        "summary": summary,
        "warnings": _formula_warnings(sheet),
        "metrics": {**metrics, "formula_count": str(len(sheet.get("formulas") or []))},
    }


def _add_sheet(sheets: list[dict], text: str) -> dict:
    name = _capture(text, r"برگه\s+(.+?)\s+را اضافه")
    if not name:
        return _ask(PLAN_NEED_NAME)
    if _find_sheet(sheets, name):
        return _ask(PLAN_SHEET_EXISTS)
    cloned = _clone(sheets)
    cloned.append({"name": name, "rows": [[name]], "formulas": set(), "bold_header": True, "freeze": "A2"})
    metrics = {"sheet_count": str(len(cloned))}
    return {"sheets": cloned, "summary": render("فایل اکنون {sheet_count} برگه دارد.", metrics), "warnings": [], "metrics": metrics}


def _delete_sheet(sheets: list[dict], text: str) -> dict:
    if len(sheets) < 2:
        return _ask(PLAN_ONE_SHEET)
    name = _capture(text, r"برگه\s+(.+?)\s+را حذف")
    if not name:
        return _ask(PLAN_NEED_NAME)
    target = _find_sheet(sheets, name)
    if target is None:
        return _ask(PLAN_NEED_SHEET)
    kept = [sheet for sheet in _clone(sheets) if _norm(sheet["name"]) != _norm(name)]
    metrics = {"sheet_count": str(len(kept))}
    return {"sheets": kept, "summary": render("فایل اکنون {sheet_count} برگه دارد.", metrics), "warnings": [], "metrics": metrics}


def _rename_sheet(sheets: list[dict], text: str) -> dict:
    match = re.search(r"نام برگه\s+(.+?)\s+را\s+(.+?)\s+بگذار", text)
    if not match or not _safe_name(match.group(1)) or not _safe_name(match.group(2)):
        return _ask(PLAN_NEED_NAME)
    source, target = match.group(1).strip(), match.group(2).strip()
    if _find_sheet(sheets, source) is None:
        return _ask(PLAN_NEED_SHEET)
    if _norm(source) != _norm(target) and _find_sheet(sheets, target):
        return _ask(PLAN_SHEET_EXISTS)
    cloned = _clone(sheets)
    for sheet in cloned:
        if _norm(sheet["name"]) == _norm(source):
            sheet["name"] = target
    metrics = {"sheet_count": str(len(cloned))}
    return {"sheets": cloned, "summary": render("نام برگه عوض شد. فایل {sheet_count} برگه دارد.", metrics), "warnings": [], "metrics": metrics}


def _move_sheet(sheets: list[dict], text: str) -> dict:
    name = _capture(text, r"برگه\s+(.+?)\s+را (?:اول|جابجا)")
    if not name:
        return _ask(PLAN_NEED_NAME)
    if _find_sheet(sheets, name) is None:
        return _ask(PLAN_NEED_SHEET)
    cloned = _clone(sheets)
    index = next(i for i, sheet in enumerate(cloned) if _norm(sheet["name"]) == _norm(name))
    chosen = cloned.pop(index)
    cloned.insert(0, chosen)
    metrics = {"sheet_count": str(len(cloned))}
    return {"sheets": cloned, "summary": render("برگه در جایگاه اول است. فایل {sheet_count} برگه دارد.", metrics), "warnings": [], "metrics": metrics}


def _add_column(sheets: list[dict]) -> dict:
    cloned = _clone(sheets)
    sheet = _main(cloned)
    if not sheet["rows"]:
        return _ask(PLAN_NO_ROW)
    if any(_norm(cell) == _norm("تازه") for cell in sheet["rows"][0]):
        return _ask(PLAN_SHEET_EXISTS)
    width = len(sheet["rows"][0])
    for index, row in enumerate(sheet["rows"]):
        row.append("تازه" if index == 0 else "")
        if len(row) < width + 1:
            row.extend([""] * (width + 1 - len(row)))
    metrics = {"column_count": str(len(sheet["rows"][0]))}
    return {"sheets": cloned, "summary": render("ستون تازه اضافه شد. برگه {column_count} ستون دارد.", metrics), "warnings": [], "metrics": metrics}


def _delete_column(sheets: list[dict], text: str) -> dict:
    name = _capture(text, r"ستون\s+(.+?)\s+را حذف")
    if not name:
        return _ask(PLAN_NEED_NAME)
    cloned = _clone(sheets)
    sheet = _sheet_with_header(cloned, name)
    if sheet is None:
        return _ask(PLAN_NEED_HEADER)
    header = sheet["rows"][0]
    if len(header) < 2:
        return _ask(PLAN_ONE_COLUMN)
    index = _header_index(header, name)
    warnings = _formula_warnings(sheet)
    metrics = {"formula_count": str(len(sheet.get("formulas") or [])), "column_count": str(len(header) - 1)}
    _drop_formulas(sheet)
    for row in sheet["rows"]:
        if index < len(row):
            del row[index]
    return {
        "sheets": cloned,
        "summary": render("ستون حذف شد. برگه {column_count} ستون دارد.", metrics),
        "warnings": warnings,
        "metrics": metrics,
    }


def _move_column(sheets: list[dict], text: str) -> dict:
    name = _capture(text, r"ستون\s+(.+?)\s+را (?:اول|جابجا)")
    if not name:
        return _ask(PLAN_NEED_NAME)
    cloned = _clone(sheets)
    sheet = _sheet_with_header(cloned, name)
    if sheet is None:
        return _ask(PLAN_NEED_HEADER)
    index = _header_index(sheet["rows"][0], name)
    warnings = _formula_warnings(sheet)
    metrics = {"formula_count": str(len(sheet.get("formulas") or [])), "column_count": str(len(sheet["rows"][0]))}
    _drop_formulas(sheet)
    for row in sheet["rows"]:
        if index < len(row):
            row.insert(0, row.pop(index))
    return {
        "sheets": cloned,
        "summary": render("ستون در جایگاه اول است. برگه {column_count} ستون دارد.", metrics),
        "warnings": warnings,
        "metrics": metrics,
    }


def _add_row(sheets: list[dict]) -> dict:
    cloned = _clone(sheets)
    sheet = _main(cloned)
    if not sheet["rows"]:
        return _ask(PLAN_NO_ROW)
    warnings = _formula_warnings(sheet)
    metrics = {"formula_count": str(len(sheet.get("formulas") or [])), "row_count": str(len(sheet["rows"]))}
    _drop_formulas(sheet)
    width = max(len(row) for row in sheet["rows"])
    sheet["rows"].insert(1, [""] * width)
    metrics["row_count"] = str(len(sheet["rows"]) - 1)
    return {
        "sheets": cloned,
        "summary": render("یک ردیف اضافه شد. برگه {row_count} ردیف داده دارد.", metrics),
        "warnings": warnings,
        "metrics": metrics,
    }


def _delete_row(sheets: list[dict]) -> dict:
    cloned = _clone(sheets)
    sheet = _main(cloned)
    if len(sheet["rows"]) < 2:
        return _ask(PLAN_NO_ROW)
    formula_count = len(sheet.get("formulas") or [])
    warnings = _formula_warnings(sheet)
    _drop_formulas(sheet)
    sheet["rows"].pop()
    metrics = {"formula_count": str(formula_count), "row_count": str(len(sheet["rows"]) - 1)}
    return {
        "sheets": cloned,
        "summary": render("یک ردیف حذف شد. برگه {row_count} ردیف داده دارد.", metrics),
        "warnings": warnings,
        "metrics": metrics,
    }


def _format(sheets: list[dict], text: str) -> dict:
    cloned = _clone(sheets)
    if "گروهبندی" in text:
        sheet = _main(cloned)
        if len(sheet["rows"]) < 2:
            return _ask(PLAN_NO_GROUP)
        sheet["outline"] = {"start": 2, "end": len(sheet["rows"])}
        metrics = {"row_count": str(len(sheet["rows"]) - 1)}
        return {
            "sheets": cloned,
            "summary": render("{row_count} ردیف داده گروه‌بندی شد.", metrics),
            "warnings": [],
            "metrics": metrics,
        }
    for sheet in cloned:
        sheet["bold_header"] = True
    metrics = {"sheet_count": str(len(cloned))}
    return {"sheets": cloned, "summary": render("سرستون {sheet_count} برگه پررنگ شد.", metrics), "warnings": [], "metrics": metrics}


def _freeze(sheets: list[dict]) -> dict:
    cloned = _clone(sheets)
    for sheet in cloned:
        sheet["freeze"] = "A2"
    metrics = {"sheet_count": str(len(cloned))}
    return {"sheets": cloned, "summary": render("سطر عنوان در {sheet_count} برگه تثبیت شد.", metrics), "warnings": [], "metrics": metrics}


def _validate(sheets: list[dict]) -> dict:
    cloned = _clone(sheets)
    found = []
    for sheet in cloned:
        if not sheet["rows"]:
            continue
        index = _header_contains(sheet["rows"][0], "شهر")
        if index is not None:
            found.append((sheet, index))
    if not found:
        return _ask(PLAN_NO_CITY)
    if len(found) > 1:
        return _ask("بیش از یک ستون شهر هست. کدام برگه را بگیرم؟")
    sheet, index = found[0]
    letter = _letter(index)
    sheet["validation"] = {"values": list(_CITIES), "sqref": f"{letter}2:{letter}200"}
    metrics = {"choice_count": str(len(_CITIES))}
    return {
        "sheets": cloned,
        "summary": render("فهرست کشویی با {choice_count} شهر روی ستون شهر ساخته شد.", metrics),
        "warnings": [],
        "metrics": metrics,
    }


def _export(sheets: list[dict]) -> dict:
    sheet = _main(sheets)
    safe, neutralized = neutralize_rows(sheet["rows"])
    metrics = {"data_rows": str(max(len(safe) - 1, 0)), "neutralized": str(neutralized)}
    warnings = []
    if neutralized:
        warnings.append(render("{neutralized} خانه در خروجی csv بی‌اثر شد.", metrics))
    return {
        "sheets": [{"name": "خروجی", "rows": safe, "formulas": set()}],
        "summary": render("{data_rows} ردیف در خروجی csv نوشته شد.", metrics),
        "warnings": warnings,
        "metrics": metrics,
        "file_format": "csv",
        "filename": "خروجی.csv",
    }


def _formula_warnings(sheet: dict) -> list[str]:
    count = len(sheet.get("formulas") or [])
    if not count:
        return []
    metrics = {"formula_count": str(count)}
    return [render("{formula_count} فرمول به‌صورت متن ماند تا ارجاع جابه‌جا شده اجرا نشود.", metrics)]


def _drop_formulas(sheet: dict) -> None:
    sheet["formulas"] = set()


def _mismatch_count(sheet: dict) -> int:
    grouped: dict[int, list[str]] = {}
    rows = sheet["rows"]
    for row_index, column_index in sheet.get("formulas") or []:
        if row_index == 0 or row_index >= len(rows) or column_index >= len(rows[row_index]):
            continue
        value = rows[row_index][column_index]
        if not isinstance(value, str):
            continue
        grouped.setdefault(column_index, []).append(_CELL_REF.sub(lambda match: match.group(1) + "#", value))
    mismatch = 0
    for patterns in grouped.values():
        if len(patterns) < 2:
            continue
        winner = max(set(patterns), key=patterns.count)
        mismatch += sum(pattern != winner for pattern in patterns)
    return mismatch


def _neutralize(value) -> tuple[object, bool]:
    if not isinstance(value, str) or not value:
        return value, False
    if value[0] in _DANGER_START or value[0] in _BIDI:
        return "'" + value, True
    return value, False


def _text_columns(header: list) -> list[int]:
    found = []
    for index, name in enumerate(header, start=1):
        if _norm(name) in {_norm(item) for item in _IDENTIFIER_HEADERS}:
            found.append(index)
    return found


def _same_header(left: list, right: list) -> bool:
    return [_norm(item) for item in left] == [_norm(item) for item in right]


def _clone(sheets: list[dict]) -> list[dict]:
    cloned = []
    for sheet in sheets:
        cloned.append(
            {
                "name": sheet["name"],
                "rows": [list(row) for row in sheet["rows"]],
                "formulas": set(sheet.get("formulas") or []),
            }
        )
    return cloned


def _main(sheets: list[dict]) -> dict:
    return max(sheets, key=lambda sheet: max(len(sheet.get("rows") or []) - 1, 0))


def _find_sheet(sheets: list[dict], name: str) -> dict | None:
    for sheet in sheets:
        if _norm(sheet["name"]) == _norm(name):
            return sheet
    return None


def _sheet_with_header(sheets: list[dict], name: str) -> dict | None:
    for sheet in sheets:
        if sheet.get("rows") and _header_index(sheet["rows"][0], name) is not None:
            return sheet
    return None


def _header_index(header: list, name: str) -> int | None:
    for index, cell in enumerate(header):
        if _norm(cell) == _norm(name):
            return index
    return None


def _header_contains(header: list, needle: str) -> int | None:
    for index, cell in enumerate(header):
        if needle in _norm(cell):
            return index
    return None


def _capture(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text)
    if not match:
        return None
    name = match.group(1).strip()
    if not _safe_name(name):
        return None
    return name


def _safe_name(name: str) -> bool:
    if not name or len(name) > 31:
        return False
    return not any(char in name for char in _UNSAFE_NAME)


def _letter(index: int) -> str:
    number = index + 1
    letters = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _norm(value) -> str:
    text = "" if value is None else str(value)
    return text.replace("ي", "ی").replace("ى", "ی").replace("ك", "ک").replace("\u200c", "").strip()


def _ask(question: str) -> dict:
    return {"question": question}
