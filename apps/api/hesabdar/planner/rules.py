from __future__ import annotations

import re
import uuid
from decimal import Decimal

from hesabdar.errors import AppError
from hesabdar.inspection.classify import translate_digits
from hesabdar.messages import (
    PLAN_MULTI,
    PLAN_NEED_AMOUNT,
    PLAN_NEED_FILE,
    PLAN_NEED_FILES,
    PLAN_QUESTION,
    PLAN_REJECTED,
    REQUEST_EMPTY,
    REQUEST_INVALID,
)
from hesabdar.planner.validate import looks_like_code

_UNITS = {"هزار": Decimal(1_000), "میلیون": Decimal(1_000_000), "میلیارد": Decimal(1_000_000_000)}
_COMPARISONS = (
    ("بیشتر از", "gt", "بیشتر از"),
    ("کمتر از", "lt", "کمتر از"),
    ("حداقل", "gte", "حداقل"),
    ("حداکثر", "lte", "حداکثر"),
)
_MAX_TEXT = 2000


def build_plan(user_text: str, workspace_id: str, file_ids: list[str]) -> dict:
    """فقط متن درخواست را می‌خواند. محتوای سلول هرگز به اینجا نمی‌رسد."""

    text = user_text.strip()
    if not text:
        raise AppError("request.invalid", REQUEST_EMPTY, 400)
    if looks_like_code(text):
        raise AppError("plan.unknown_tool", PLAN_REJECTED, 422)
    if len(text) > _MAX_TEXT:
        raise AppError("request.invalid", REQUEST_INVALID, 400)
    normal = _normalize(text)
    plan = _empty_plan(text, workspace_id)
    signal = _signal(normal)
    if signal is None:
        return _ask(plan, PLAN_QUESTION)
    if signal == "many":
        return _ask(plan, PLAN_MULTI)
    if signal == "amount":
        return _ask(plan, PLAN_NEED_AMOUNT)
    tool, params = _params(signal, normal, file_ids)
    if tool is None:
        return _ask(plan, params["question"])
    if tool not in {"inspect", "preview"}:
        targets = file_ids if tool == "reconcile" else file_ids[:1]
        for file_id in targets:
            plan["steps"].append(_step("inspect", {"file_id": file_id}, [file_id], []))
    plan["steps"].append(_step(tool, params, list(file_ids), ["result"]))
    plan["goal"] = tool
    return plan


def _signal(normal: str) -> str | None:
    found = []
    if "درصد اختلاف" in normal:
        found.append("compute_column")
    if "تطبیق" in normal or "مغایرت" in normal:
        found.append("reconcile")
    if "پاکسازی" in normal:
        found.append("clean")
    if "مرتب" in normal and "مبلغ" in normal:
        found.append("sort")
    amount = _comparison(normal)
    if amount == "missing" and ("فروش" in normal or "مبلغ" in normal):
        found.append("amount")
    elif isinstance(amount, dict) and ("فروش" in normal or "مبلغ" in normal):
        found.append("filter")
    if "ستون" in normal and "اضافه" in normal and "درصد اختلاف" not in normal:
        found.append("add_column")
    if "پیشنمایش" in normal:
        found.append("preview")
    if "بررسی" in normal and "ساختار" in normal:
        found.append("inspect")
    if not found:
        return None
    if len(found) > 1:
        return "many"
    return found[0]


def _params(tool: str, normal: str, file_ids: list[str]) -> tuple[str | None, dict]:
    if tool == "reconcile":
        if len(file_ids) != 2:
            return None, {"question": PLAN_NEED_FILES}
        return tool, {"left_file_id": file_ids[0], "right_file_id": file_ids[1], "key_columns": []}
    if len(file_ids) != 1:
        return None, {"question": PLAN_NEED_FILE}
    file_id = file_ids[0]
    if tool == "filter":
        parsed = _comparison(normal)
        return tool, {"file_id": file_id, "op": parsed["op"], "value": parsed["value"], "label": parsed["label"]}
    if tool == "sort":
        return tool, {"file_id": file_id, "direction": "desc"}
    if tool == "compute_column":
        return tool, {"file_id": file_id, "name": "درصد اختلاف"}
    if tool == "add_column":
        match = re.search(r"ستون\s+(.+?)\s+را اضافه", normal)
        name = match.group(1).strip() if match else ""
        if not name or len(name) > 40 or looks_like_code(name):
            return None, {"question": PLAN_QUESTION}
        return tool, {"file_id": file_id, "name": name}
    if tool in {"clean", "preview", "inspect"}:
        return tool, {"file_id": file_id}
    return None, {"question": PLAN_QUESTION}


def _comparison(normal: str):
    hits = []
    for phrase, op, label in _COMPARISONS:
        for match in re.finditer(rf"{re.escape(phrase)}\s+(\d+)(?:\s*(میلیارد|میلیون|هزار))?", normal):
            hits.append((op, label, match))
    if not hits:
        if any(phrase in normal for phrase, _op, _label in _COMPARISONS):
            return "missing"
        return None
    if len(hits) != 1:
        return "missing"
    op, label, match = hits[0]
    value = Decimal(match.group(1))
    unit = match.group(2)
    if unit:
        value *= _UNITS[unit]
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return {"op": op, "label": label, "value": rendered}


def _normalize(value: str) -> str:
    text = translate_digits(value)
    text = text.replace("ي", "ی").replace("ى", "ی").replace("ك", "ک")
    text = text.replace("\u200c", "").replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _empty_plan(user_text: str, workspace_id: str) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "workspace_id": workspace_id,
        "user_text": user_text,
        "goal": "",
        "steps": [],
        "ambiguities": [],
        "requires_confirmation": False,
        "confirmation_reasons": [],
        "risks": [],
        "source": "rules",
    }


def _ask(plan: dict, question: str) -> dict:
    plan["ambiguities"] = [{"code": "plan.ambiguous", "question": question, "choices": []}]
    return plan


def _step(tool: str, params: dict, reads: list[str], writes: list[str]) -> dict:
    return {"tool": tool, "params": params, "reads": reads, "writes": writes}
