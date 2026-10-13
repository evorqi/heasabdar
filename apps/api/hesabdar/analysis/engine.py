from __future__ import annotations

import re
from decimal import Decimal

from hesabdar.inspection.classify import classify_date, normalize_letters, parse_number, role_from_header, translate_digits
from hesabdar.messages import (
    PLAN_NO_AMOUNT,
    PLAN_NO_CITY,
    PLAN_NO_DATE,
    PLAN_NO_SPREAD,
    PLAN_NO_VALUES,
    PLAN_SMALL_SAMPLE,
)
from hesabdar.planner.explain import render

_MONEY = "مبلغ"
_COUNT = "تعداد"
_PERCENT = "درصد"


def role_columns(table: dict, role: str) -> list[str]:
    found = []
    for name in table["headers"]:
        if table["roles"].get(name) == role or role_from_header(name) == role:
            if name not in found:
                found.append(name)
    return found


def analyze(table: dict, amount_column: str) -> dict:
    points = []
    invalid = 0
    for index, row in enumerate(table["rows"], start=1):
        raw = row.get(amount_column)
        if raw not in (None, ""):
            raw = str(raw)
        amount, warning = parse_number(raw) if raw not in (None, "") else (None, None)
        if raw not in (None, "") and (warning or amount is None):
            invalid += 1
            continue
        if amount is None:
            continue
        points.append({"row": index, "amount": amount, "city": _text(row, role_columns(table, "city")), "date": _period(row, role_columns(table, "date"))})
    amounts = [point["amount"] for point in points]
    stats = _stats(amounts) if amounts else None
    return {
        "points": points,
        "invalid": invalid,
        "stats": stats,
        "cities": _groups(points, "city"),
        "periods": _groups(points, "date"),
        "city_columns": role_columns(table, "city"),
        "date_columns": role_columns(table, "date"),
    }


def present(analysis: dict, tool: str) -> dict:
    blocked = _blocked(analysis, tool)
    if blocked:
        return {"blocked": blocked, "summary": None, "metrics": {}, "warnings": [], "cards": [], "sheets": [], "filename": ""}
    built = _build(analysis, tool)
    summary = render(built["template"], built["metrics"])
    return {
        "blocked": None,
        "summary": summary,
        "metrics": built["metrics"],
        "warnings": built["warnings"],
        "cards": built["cards"],
        "sheets": built["sheets"],
        "filename": built["filename"],
    }


def _blocked(analysis: dict, tool: str) -> str | None:
    if analysis["stats"] is None:
        return PLAN_NO_VALUES if analysis["invalid"] else PLAN_NO_AMOUNT
    if tool == "rank" and not analysis["city_columns"]:
        return PLAN_NO_CITY
    if tool == "rank" and not analysis["cities"]:
        return PLAN_NO_CITY
    if tool == "trend" and not analysis["date_columns"]:
        return PLAN_NO_DATE
    if tool == "trend" and not analysis["periods"]:
        return PLAN_NO_DATE
    if tool == "outliers":
        status = _outlier_status(analysis)
        if status == "small":
            return PLAN_SMALL_SAMPLE
        if status == "flat":
            return PLAN_NO_SPREAD
    return None


def _build(analysis: dict, tool: str) -> dict:
    stats = analysis["stats"]
    metrics = {
        "total": stats["total"],
        "mean": stats["mean"],
        "median": stats["median"],
        "minimum": stats["minimum"],
        "maximum": stats["maximum"],
        "valid_rows": stats["valid_rows"],
    }
    cards = [
        _card("total", "مجموع", metrics["total"], _MONEY, False),
        _card("mean", "میانگین", metrics["mean"], _MONEY, False),
        _card("median", "میانه", metrics["median"], _MONEY, False),
        _card("minimum", "کمینه", metrics["minimum"], _MONEY, False),
        _card("maximum", "بیشینه", metrics["maximum"], _MONEY, False),
        _card("valid_rows", "ردیف معتبر", metrics["valid_rows"], _COUNT, False),
    ]
    warnings = []
    gaps = []
    groups = []
    outlier_rows = []
    if analysis["invalid"]:
        metrics["invalid_amounts"] = str(analysis["invalid"])
        warnings.append(render("{invalid_amounts} مبلغ نامعتبر در محاسبه نیامد.", metrics))
    if tool in {"rank", "report"}:
        _add_rank(analysis, metrics, cards, warnings, gaps, groups, required=tool == "rank")
    if tool in {"trend", "report"}:
        _add_trend(analysis, metrics, cards, warnings, gaps, groups, required=tool == "trend")
    if tool in {"outliers", "report"}:
        _add_outliers(analysis, metrics, cards, warnings, gaps, outlier_rows, required=tool == "outliers")
    if tool == "kpi":
        cards = [card for card in cards if card["name"] in {"total", "mean", "valid_rows"}]
    if tool == "aggregate":
        gaps = []
        groups = []
        outlier_rows = []
    if tool == "rank":
        cards = [card for card in cards if card["name"] in {"top_city", "top_total", "tie_count", "valid_rows"}]
        gaps = [gap for gap in gaps if gap[0] == "رتبه"]
    if tool == "trend":
        cards = [card for card in cards if card["name"] in {"period_count", "last_total", "growth", "valid_rows"}]
        gaps = [gap for gap in gaps if gap[0] in {"روند", "رشد"}]
    if tool == "outliers":
        cards = [card for card in cards if card["name"] == "outlier_count"]
    template = _template(tool, metrics)
    sheets = _sheets(cards, groups, outlier_rows, gaps)
    return {
        "template": template,
        "metrics": metrics,
        "warnings": warnings,
        "cards": cards,
        "sheets": sheets,
        "filename": _FILENAME[tool],
    }


def _template(tool: str, metrics: dict[str, str]) -> str:
    if tool == "rank":
        if "tie_count" in metrics:
            return "بیشترین فروش برای {tie_count} شهر مساوی است و مجموع هر کدام {top_total} است."
        return "بیشترین فروش برای {top_city} است و مجموع آن {top_total} است."
    if tool == "trend":
        text = "{period_count} دوره دیده شد. مجموع دوره آخر {last_total} است."
        if "growth" in metrics:
            text += " تغییر نسبت به دوره قبل {growth} درصد است."
        return text
    if tool == "outliers":
        if "outlier_count" not in metrics:
            return "مقدار پرتی با این حصار دیده نشد. فاصله از جمع، غلط بودن مقدار را ثابت نمی‌کند."
        return "{outlier_count} مقدار با برچسب احتمال جدا شد. فاصله از جمع، غلط بودن مقدار را ثابت نمی‌کند."
    if tool == "kpi":
        return "{valid_rows} ردیف، مجموع {total} و میانگین {mean}."
    text = "مجموع {total}، میانگین {mean}، میانه {median}، کمینه {minimum} و بیشینه {maximum} است."
    if tool == "report" and "top_total" in metrics and "tie_count" in metrics:
        text += " بیشترین فروش برای {tie_count} شهر مساوی است و مجموع هر کدام {top_total} است."
    elif tool == "report" and "top_total" in metrics:
        text += " بیشترین فروش برای {top_city} است و مجموع آن {top_total} است."
    if tool == "report" and "growth" in metrics:
        text += " تغییر دو دوره آخر {growth} درصد است."
    if tool == "report" and "outlier_count" in metrics:
        text += " {outlier_count} مقدار با برچسب احتمال جدا شد."
    return text


def _add_rank(analysis: dict, metrics: dict, cards: list, warnings: list, gaps: list, groups: list, required: bool) -> None:
    if not analysis["city_columns"] or not analysis["cities"]:
        gaps.append(("رتبه", "شهر"))
        gaps.append(("توزیع", "شهر"))
        gaps.append(("مقایسه", "شهر"))
        if required:
            return
        warnings.append("رتبه قابل محاسبه نیست. ستون شهر نیست.")
        return
    ranked = sorted(analysis["cities"], key=lambda item: (item["amount"], item["label"]), reverse=True)
    top = ranked[0]["amount"]
    winners = [item for item in ranked if item["amount"] == top]
    metrics["top_total"] = _plain(top)
    cards.append(_card("top_total", "مجموع شهر برتر", metrics["top_total"], _MONEY, False))
    if len(winners) == 1:
        metrics["top_city"] = winners[0]["label"]
        cards.append(_card("top_city", "شهر برتر", metrics["top_city"], "شهر", False))
    else:
        metrics["tie_count"] = str(len(winners))
        cards.append(_card("tie_count", "شهرهای هم‌امتیاز", metrics["tie_count"], _COUNT, False))
    total = sum((item["amount"] for item in ranked), Decimal(0))
    for item in ranked:
        share = (item["amount"] / total) * Decimal(100) if total != 0 else None
        groups.append(
            {
                "kind": "city",
                "label": item["label"],
                "value": _plain(item["amount"]),
                "share": _plain(share.quantize(Decimal("0.0001"))) if share is not None else "",
            }
        )
    skipped = [point for point in analysis["points"] if point["city"] is None]
    if skipped:
        warnings.append("بعضی ردیف‌ها شهر نداشتند و در رتبه نیامدند.")


def _add_trend(analysis: dict, metrics: dict, cards: list, warnings: list, gaps: list, groups: list, required: bool) -> None:
    if not analysis["date_columns"] or not analysis["periods"]:
        gaps.append(("روند", "تاریخ"))
        gaps.append(("رشد", "تاریخ"))
        if not required:
            warnings.append("روند قابل محاسبه نیست. ستون تاریخ نیست.")
        return
    periods = sorted(analysis["periods"], key=lambda item: item["key"])
    metrics["period_count"] = str(len(periods))
    metrics["last_total"] = _plain(periods[-1]["amount"])
    cards.append(_card("period_count", "تعداد دوره", metrics["period_count"], _COUNT, False))
    cards.append(_card("last_total", "مجموع دوره آخر", metrics["last_total"], _MONEY, False))
    for item in periods:
        groups.append({"kind": "period", "label": item["label"], "value": _plain(item["amount"])})
    if len(periods) < 2:
        gaps.append(("رشد", "دو دوره"))
        warnings.append("رشد قابل محاسبه نیست. دو دوره لازم است.")
        return
    previous = periods[-2]["amount"]
    if previous == 0:
        gaps.append(("رشد", "دوره قبل"))
        warnings.append("رشد قابل محاسبه نیست. مبلغ دوره قبل صفر است.")
        return
    growth = ((periods[-1]["amount"] - previous) / abs(previous)) * Decimal(100)
    metrics["growth"] = _plain(growth.quantize(Decimal("0.0001")))
    cards.append(_card("growth", "تغییر دوره", metrics["growth"], _PERCENT, False))


def _add_outliers(analysis: dict, metrics: dict, cards: list, warnings: list, gaps: list, outlier_rows: list, required: bool) -> None:
    status = _outlier_status(analysis)
    if status == "small":
        gaps.append(("پرت", "نمونه"))
        if not required:
            warnings.append("پرت قابل محاسبه نیست. نمونه کم است.")
        return
    if status == "flat":
        gaps.append(("پرت", "پراکندگی"))
        if not required:
            warnings.append("پرت قابل محاسبه نیست. پراکندگی کافی نیست.")
        return
    low, high = _fences([point["amount"] for point in analysis["points"]])
    found = [point for point in analysis["points"] if point["amount"] < low or point["amount"] > high]
    if not found:
        gaps.append(("پرت", "مقدار خارج از حصار"))
        warnings.append("مقدار پرتی با این حصار دیده نشد.")
        return
    metrics["outlier_count"] = str(len(found))
    cards.append(_card("outlier_count", "پرت", metrics["outlier_count"], _COUNT, True))
    for point in found:
        outlier_rows.append({"row": str(point["row"]), "value": _plain(point["amount"])})
    warnings.append("فاصله از جمع، غلط بودن مقدار را ثابت نمی‌کند.")


def _outlier_status(analysis: dict) -> str:
    amounts = [point["amount"] for point in analysis["points"]]
    if len(amounts) < 4:
        return "small"
    low, high = _fences(amounts)
    if low == high:
        return "flat"
    return "ok"


def _fences(amounts: list[Decimal]) -> tuple[Decimal, Decimal]:
    ordered = sorted(amounts)
    quartile_low = _percentile(ordered, Decimal("0.25"))
    quartile_high = _percentile(ordered, Decimal("0.75"))
    spread = quartile_high - quartile_low
    return quartile_low - (Decimal("1.5") * spread), quartile_high + (Decimal("1.5") * spread)


def _percentile(ordered: list[Decimal], portion: Decimal) -> Decimal:
    if len(ordered) == 1:
        return ordered[0]
    position = Decimal(len(ordered) - 1) * portion
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - Decimal(lower)
    if fraction == 0:
        return ordered[lower]
    return ordered[lower] * (Decimal(1) - fraction) + ordered[upper] * fraction


def _stats(amounts: list[Decimal]) -> dict[str, str]:
    ordered = sorted(amounts)
    total = sum(amounts, Decimal(0))
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        median = ordered[middle]
    else:
        median = (ordered[middle - 1] + ordered[middle]) / 2
    mean = total / Decimal(len(ordered))
    return {
        "total": _plain(total),
        "mean": _plain(mean),
        "median": _plain(median),
        "minimum": _plain(ordered[0]),
        "maximum": _plain(ordered[-1]),
        "valid_rows": str(len(ordered)),
    }


def _groups(points: list[dict], field: str) -> list[dict]:
    buckets: dict[str, dict] = {}
    for point in points:
        value = point[field]
        if value is None:
            continue
        key, label = value
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {"key": key, "label": label, "amount": Decimal(0)}
            buckets[key] = bucket
        bucket["amount"] += point["amount"]
    return list(buckets.values())


def _text(row: dict, columns: list[str]):
    if len(columns) != 1:
        return None
    raw = row.get(columns[0])
    if raw in (None, ""):
        return None
    label = str(raw).strip()
    if not label:
        return None
    key = re.sub(r"\s+", " ", translate_digits(normalize_letters(label))).strip()
    return key, label


def _period(row: dict, columns: list[str]):
    if len(columns) != 1:
        return None
    raw = row.get(columns[0])
    if raw in (None, ""):
        return None
    parsed, warning = classify_date(str(raw))
    if warning or not parsed or len(parsed) < 7:
        return None
    period = parsed[:7]
    return period, period


def _sheets(cards: list[dict], groups: list[dict], outlier_rows: list[dict], gaps: list[tuple[str, str]]) -> list[dict]:
    sheets = []
    if cards:
        sheets.append(
            {
                "name": "شاخص‌ها",
                "rows": [["شاخص", "مقدار", "واحد", "برچسب"]]
                + [[card["label"], card["value"], card["unit"], "احتمال" if card["hypothesis"] else "محاسبه"] for card in cards],
            }
        )
    cities = [item for item in groups if item["kind"] == "city"]
    periods = [item for item in groups if item["kind"] == "period"]
    if cities:
        sheets.append(
            {
                "name": "شهرها",
                "rows": [["شهر", "مجموع", "سهم"]] + [[item["label"], item["value"], item["share"]] for item in cities],
            }
        )
    if periods:
        sheets.append(
            {
                "name": "دوره‌ها",
                "rows": [["دوره", "مجموع"]] + [[item["label"], item["value"]] for item in periods],
            }
        )
    if outlier_rows:
        sheets.append(
            {
                "name": "پرت",
                "rows": [["ردیف", "مقدار", "برچسب"]] + [[item["row"], item["value"], "احتمال"] for item in outlier_rows],
            }
        )
    if gaps:
        sheets.append(
            {
                "name": "محدودیت‌ها",
                "rows": [["شاخص", "وضعیت", "ستون"]] + [[label, "قابل محاسبه نیست", column] for label, column in gaps],
            }
        )
    return sheets


def _card(name: str, label: str, value: str, unit: str, hypothesis: bool) -> dict:
    return {"name": name, "label": label, "value": value, "unit": unit, "hypothesis": hypothesis}


def _plain(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


_FILENAME = {
    "aggregate": "شاخص.xlsx",
    "kpi": "شاخص.xlsx",
    "rank": "رتبه.xlsx",
    "trend": "روند.xlsx",
    "outliers": "پرت.xlsx",
    "report": "گزارش.xlsx",
}
