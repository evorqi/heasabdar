from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from difflib import SequenceMatcher

from hesabdar.inspection.classify import IDENTIFIER_ROLES
from hesabdar.reconcile.normalize import header_key, normalize_compare, parse_amount

NAME_SIMILARITY = Decimal("0.80")
CLEAR_GAP = Decimal("0.15")


def load_table(read_sheet, summary: dict) -> dict:
    headers = [column["name"] for column in summary["columns"]]
    roles = [column["role_hints"][0] if column["role_hints"] else None for column in summary["columns"]]
    start = summary["header_row_index"] + 1
    rows = []
    for row in read_sheet.rows[start:]:
        item = {}
        for index, header in enumerate(headers):
            cell = row[index] if index < len(row) else None
            item[header] = None if cell is None else cell.raw
        rows.append(item)
    return {
        "sheet": read_sheet.name,
        "headers": headers,
        "roles": dict(zip(headers, roles, strict=True)),
        "rows": rows,
    }


def suggest_keys(left: dict, right: dict) -> dict:
    pairs = _align(left, right)
    scored = []
    for left_name, right_name, role in pairs:
        score = _score(role, [row.get(left_name) for row in left["rows"]], [row.get(right_name) for row in right["rows"]])
        scored.append({"column": left_name, "score": score, "role": role})
    scored.sort(key=lambda item: item["score"], reverse=True)
    if not scored or scored[0]["score"] < Decimal("0.60"):
        return {"ambiguous": True, "choices": [item["column"] for item in scored], "keys": []}
    if len(scored) > 1 and scored[0]["score"] - scored[1]["score"] < CLEAR_GAP:
        close = [item["column"] for item in scored if scored[0]["score"] - item["score"] < CLEAR_GAP]
        return {"ambiguous": True, "choices": close, "keys": []}
    return {"ambiguous": False, "choices": [scored[0]["column"]], "keys": [scored[0]["column"]]}


def reconcile(left: dict, right: dict, key_columns: list[str]) -> dict:
    alignment = {left_name: right_name for left_name, right_name, _role in _align(left, right)}
    missing = [name for name in key_columns if name not in alignment]
    if missing:
        return {"error": "key.missing", "missing": missing}
    amount_left = _amount_column(left)
    amount_right = _amount_column(right)
    name_left = _name_column(left)
    name_right = _name_column(right)
    right_amount_name = alignment.get(amount_left) if amount_left else None
    right_name_name = alignment.get(name_left) if name_left else None

    def key_of(row: dict, columns: list[str], side_alignment: dict[str, str] | None) -> str | None:
        parts = []
        for column in columns:
            source = column if side_alignment is None else side_alignment[column]
            part = normalize_compare(row.get(source))
            if part is None:
                return None
            parts.append(part)
        return "\u241f".join(parts)

    left_groups: dict[str, list[int]] = defaultdict(list)
    right_groups: dict[str, list[int]] = defaultdict(list)
    left_unkeyed: list[int] = []
    right_unkeyed: list[int] = []
    for index, row in enumerate(left["rows"]):
        key = key_of(row, key_columns, None)
        if key is None:
            left_unkeyed.append(index)
        else:
            left_groups[key].append(index)
    for index, row in enumerate(right["rows"]):
        key = key_of(row, key_columns, alignment)
        if key is None:
            right_unkeyed.append(index)
        else:
            right_groups[key].append(index)

    rows: list[dict] = []
    only_left_pool: list[int] = list(left_unkeyed)
    only_right_pool: list[int] = list(right_unkeyed)
    for key in sorted(set(left_groups) | set(right_groups)):
        left_indexes = left_groups.get(key, [])
        right_indexes = right_groups.get(key, [])
        if left_indexes and right_indexes and len(left_indexes) == 1 and len(right_indexes) == 1:
            rows.append(
                _paired(
                    left,
                    right,
                    left_indexes[0],
                    right_indexes[0],
                    key_columns,
                    alignment,
                    amount_left,
                    right_amount_name,
                    name_left,
                    right_name_name,
                )
            )
        elif left_indexes and right_indexes:
            right_key_columns = [alignment[column] for column in key_columns]
            for index in left_indexes:
                rows.append(_ambiguous_duplicate(left, index, key_columns, amount_left, name_left, side="left"))
            for index in right_indexes:
                rows.append(
                    _ambiguous_duplicate(right, index, right_key_columns, amount_right, name_right, side="right")
                )
        elif left_indexes:
            only_left_pool.extend(left_indexes)
        else:
            only_right_pool.extend(right_indexes)

    rows.extend(
        _similar_names(
            left,
            right,
            only_left_pool,
            only_right_pool,
            key_columns,
            [alignment[column] for column in key_columns],
            amount_left,
            amount_right,
            name_left,
            name_right,
        )
    )
    summary = _summary(rows)
    return {
        "key_columns": key_columns,
        "rows": rows,
        "summary": summary,
        "validation": _validation(left, right, rows, amount_left, amount_right),
    }


def _paired(left, right, left_index, right_index, key_columns, alignment, amount_left, amount_right, name_left, name_right):
    left_row = left["rows"][left_index]
    right_row = right["rows"][right_index]
    differing = []
    for left_name, right_name in alignment.items():
        if left_name in key_columns:
            continue
        if left_name == amount_left:
            if parse_amount(left_row.get(left_name)) != parse_amount(right_row.get(right_name)):
                differing.append(left_name)
            continue
        if normalize_compare(left_row.get(left_name)) != normalize_compare(right_row.get(right_name)):
            differing.append(left_name)
    status = "value_mismatch" if differing else "full_match"
    amount_l = parse_amount(left_row.get(amount_left)) if amount_left else None
    amount_r = parse_amount(right_row.get(amount_right)) if amount_right else None
    delta, ratio, reason = _amount_diff(amount_l, amount_r)
    if status == "full_match" and not reason:
        reason = "کلید و مقدارهای مقایسه‌شده یکی‌اند."
    if status == "value_mismatch" and not reason:
        reason = "کلید یکی است و مقدار فرق دارد."
    return {
        "status": status,
        "key": " / ".join(str(left_row.get(column) or "") for column in key_columns),
        "key_left": " / ".join(str(left_row.get(column) or "") for column in key_columns),
        "key_right": " / ".join(str(right_row.get(alignment[column]) or "") for column in key_columns),
        "confidence": 1,
        "name_left": left_row.get(name_left) if name_left else None,
        "name_right": right_row.get(name_right) if name_right else None,
        "amount_left": _text(amount_l),
        "amount_right": _text(amount_r),
        "amount_delta": _text(delta),
        "amount_delta_ratio": _text(ratio),
        "reason": reason,
        "evidence": {"columns": differing},
        "left_index": left_index,
        "right_index": right_index,
    }


def _ambiguous_duplicate(table, index, key_columns, amount_column, name_column, side):
    source = table["rows"][index]
    amount = parse_amount(source.get(amount_column)) if amount_column else None
    key = " / ".join(str(source.get(column) or "") for column in key_columns)
    return {
        "status": "ambiguous",
        "key": key,
        "key_left": key if side == "left" else "",
        "key_right": key if side == "right" else "",
        "confidence": 0,
        "name_left": source.get(name_column) if side == "left" else None,
        "name_right": source.get(name_column) if side == "right" else None,
        "amount_left": _text(amount) if side == "left" else None,
        "amount_right": _text(amount) if side == "right" else None,
        "amount_delta": None,
        "amount_delta_ratio": None,
        "reason": "این کلید در فایل تکرار شده و تطبیق قطعی نیست.",
        "evidence": {},
        "left_index": index if side == "left" else None,
        "right_index": index if side == "right" else None,
    }


def _similar_names(
    left, right, left_pool, right_pool, left_key_columns, right_key_columns, amount_left, amount_right, name_left, name_right
):
    pairs = []
    for left_index in left_pool:
        for right_index in right_pool:
            score = _similarity(
                left["rows"][left_index].get(name_left) if name_left else None,
                right["rows"][right_index].get(name_right) if name_right else None,
            )
            if score >= NAME_SIMILARITY:
                pairs.append((score, left_index, right_index))
    pairs.sort(reverse=True)
    used_left = set()
    used_right = set()
    chosen = []
    for score, left_index, right_index in pairs:
        if left_index in used_left or right_index in used_right:
            continue
        used_left.add(left_index)
        used_right.add(right_index)
        chosen.append(_name_pair(left, right, left_index, right_index, score, amount_left, amount_right, name_left, name_right))
    for index in left_pool:
        if index not in used_left:
            chosen.append(_single("only_left", left["rows"][index], index, left_key_columns, amount_left, name_left))
    for index in right_pool:
        if index not in used_right:
            chosen.append(_single("only_right", right["rows"][index], index, right_key_columns, amount_right, name_right))
    return chosen


def _name_pair(left, right, left_index, right_index, score, amount_left, amount_right, name_left, name_right):
    left_row = left["rows"][left_index]
    right_row = right["rows"][right_index]
    amount_l = parse_amount(left_row.get(amount_left)) if amount_left else None
    amount_r = parse_amount(right_row.get(amount_right)) if amount_right else None
    delta, ratio, reason = _amount_diff(amount_l, amount_r)
    return {
        "status": "ambiguous",
        "key": "",
        "key_left": "",
        "key_right": "",
        "confidence": float(score),
        "name_left": left_row.get(name_left) if name_left else None,
        "name_right": right_row.get(name_right) if name_right else None,
        "amount_left": _text(amount_l),
        "amount_right": _text(amount_r),
        "amount_delta": _text(delta),
        "amount_delta_ratio": _text(ratio),
        "reason": "نام شبیه است ولی شناسه مشترک ندارد. این تطبیق قطعی نیست.",
        "evidence": {"similarity": float(score)},
        "left_index": left_index,
        "right_index": right_index,
    }


def _single(status, row, index, key_columns, amount_column, name_column):
    amount = parse_amount(row.get(amount_column)) if amount_column else None
    key = " / ".join(str(row.get(column) or "") for column in key_columns)
    return {
        "status": status,
        "key": key,
        "key_left": key if status == "only_left" else "",
        "key_right": key if status == "only_right" else "",
        "confidence": 0,
        "name_left": row.get(name_column) if status == "only_left" and name_column else None,
        "name_right": row.get(name_column) if status == "only_right" and name_column else None,
        "amount_left": _text(amount) if status == "only_left" else None,
        "amount_right": _text(amount) if status == "only_right" else None,
        "amount_delta": None,
        "amount_delta_ratio": None,
        "reason": "این ردیف فقط در فایل اول است." if status == "only_left" else "این ردیف فقط در فایل دوم است.",
        "evidence": {},
        "left_index": index if status == "only_left" else None,
        "right_index": index if status == "only_right" else None,
    }


def _amount_diff(left, right):
    if left is None or right is None:
        return None, None, "مبلغ نامعتبر است." if left is not None or right is not None else ""
    delta = abs(left - right)
    if left == 0:
        return delta, None, "مبلغ مبنای مقایسه صفر است."
    return delta, abs(delta / left), ""


def _summary(rows: list[dict]) -> dict:
    counts = {name: 0 for name in ("full_match", "value_mismatch", "only_left", "only_right", "ambiguous")}
    for row in rows:
        counts[row["status"]] += 1
    return counts


def _validation(left, right, rows, amount_left, amount_right) -> dict:
    left_ids = set()
    right_ids = set()
    for row in rows:
        if row["left_index"] is not None:
            left_ids.add(row["left_index"])
        if row["right_index"] is not None:
            right_ids.add(row["right_index"])
    identity_left = (
        _summary(rows)["full_match"]
        + _summary(rows)["value_mismatch"]
        + _summary(rows)["only_left"]
        + sum(1 for row in rows if row["status"] == "ambiguous" and row["left_index"] is not None)
    )
    identity_right = (
        _summary(rows)["full_match"]
        + _summary(rows)["value_mismatch"]
        + _summary(rows)["only_right"]
        + sum(1 for row in rows if row["status"] == "ambiguous" and row["right_index"] is not None)
    )
    left_sum = _sum(left["rows"], amount_left)
    right_sum = _sum(right["rows"], amount_right)
    categorized_left = _sum_rows(rows, "amount_left", skip_status="only_right")
    categorized_right = _sum_rows(rows, "amount_right", skip_status="only_left")
    scale = _scale(left["rows"], right["rows"], amount_left, amount_right)
    return {
        "left_rows": len(left["rows"]),
        "right_rows": len(right["rows"]),
        "identity_left": identity_left,
        "identity_right": identity_right,
        "left_amount": _text(left_sum),
        "right_amount": _text(right_sum),
        "categorized_left_amount": _text(categorized_left),
        "categorized_right_amount": _text(categorized_right),
        "scale": _text(scale),
        "rows_unique": left_ids == set(range(len(left["rows"]))) and right_ids == set(range(len(right["rows"]))),
        "ok": (
            identity_left == len(left["rows"])
            and identity_right == len(right["rows"])
            and left_ids == set(range(len(left["rows"])))
            and right_ids == set(range(len(right["rows"])))
            and abs(left_sum - categorized_left) <= scale
            and abs(right_sum - categorized_right) <= scale
        ),
    }


def _sum(rows, column):
    total = Decimal(0)
    if not column:
        return total
    for row in rows:
        amount = parse_amount(row.get(column))
        if amount is not None:
            total += amount
    return total


def _sum_rows(rows, field, skip_status):
    total = Decimal(0)
    for row in rows:
        if row["status"] == skip_status:
            continue
        if row[field] is not None:
            total += Decimal(row[field])
    return total


def _scale(left_rows, right_rows, left_column, right_column) -> Decimal:
    fractional = False
    for rows, column in ((left_rows, left_column), (right_rows, right_column)):
        if not column:
            continue
        for row in rows:
            amount = parse_amount(row.get(column))
            if amount is not None and amount != amount.to_integral_value():
                fractional = True
    return Decimal("0.01") if fractional else Decimal("1")


def _score(role, left_values, right_values) -> Decimal:
    left_keys = [key for key in (normalize_compare(value) for value in left_values) if key]
    right_keys = [key for key in (normalize_compare(value) for value in right_values) if key]
    if not left_keys or not right_keys:
        return Decimal(0)
    left_unique = Decimal(len(set(left_keys))) / Decimal(len(left_keys))
    right_unique = Decimal(len(set(right_keys))) / Decimal(len(right_keys))
    overlap = Decimal(len(set(left_keys) & set(right_keys))) / Decimal(len(set(left_keys)))
    bonus = Decimal("1") if role in IDENTIFIER_ROLES else Decimal("0.45")
    return bonus * (Decimal("0.5") * min(left_unique, right_unique) + Decimal("0.5") * overlap)


def _align(left: dict, right: dict) -> list[tuple[str, str, str | None]]:
    right_by_header = {header_key(name): name for name in right["headers"]}
    pairs = []
    for name in left["headers"]:
        other = right_by_header.get(header_key(name))
        if other:
            pairs.append((name, other, left["roles"].get(name)))
    return pairs


def _amount_column(table: dict) -> str | None:
    for name, role in table["roles"].items():
        if role == "amount":
            return name
    for name in table["headers"]:
        if "مبلغ" in header_key(name):
            return name
    return None


def _name_column(table: dict) -> str | None:
    for name, role in table["roles"].items():
        if role == "person_name":
            return name
    for name in table["headers"]:
        if header_key(name) in {"نام", "ناممشتری"}:
            return name
    return None


def _similarity(left, right) -> Decimal:
    a = normalize_compare(left)
    b = normalize_compare(right)
    if not a or not b:
        return Decimal(0)
    return Decimal(str(round(SequenceMatcher(None, a, b).ratio(), 4)))


def _text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        rendered = format(value, "f")
        if "." in rendered:
            rendered = rendered.rstrip("0").rstrip(".")
        return rendered
    return str(value)
