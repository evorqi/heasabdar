"""داشبورد فروش فقط از ستون‌هایی که واقعاً هستند. کارت بدون ستون ساخته نمی‌شود."""

from __future__ import annotations

from decimal import Decimal

from hesabdar.charts.spec import (
    _amount,
    _is_category,
    _is_product,
    _label,
    make_spec,
    plain,
    sheet_for,
)
from hesabdar.inspection.classify import compact_header
from hesabdar.messages import PLAN_NO_AMOUNT, PLAN_NO_VALUES
from hesabdar.planner.explain import render


def customer_columns(table: dict) -> list[str]:
    return [name for name in table["headers"] if "مشتری" in compact_header(name)]


def product_columns(table: dict) -> list[str]:
    return [name for name in table["headers"] if _is_product(name)]


def category_columns(table: dict) -> list[str]:
    return [name for name in table["headers"] if _is_category(name)]


def compose(table: dict, analysis: dict, picked: dict[str, str], amount_column: str) -> dict:
    if analysis["stats"] is None:
        message = PLAN_NO_VALUES if analysis["invalid"] else PLAN_NO_AMOUNT
        return {"blocked": message}
    stats = analysis["stats"]
    metrics = {"total": stats["total"], "mean": stats["mean"]}
    cards = [
        _card("total", "مجموع فروش", metrics["total"], "مبلغ"),
        _card("mean", "میانگین فروش", metrics["mean"], "مبلغ"),
    ]
    gaps = []
    warnings = []
    sheets = []
    charts = []
    _customers(table, picked.get("customer") or "", metrics, cards, gaps, warnings)
    _product(table, picked.get("product") or "", amount_column, metrics, cards, gaps, warnings, sheets)
    _cities(analysis, metrics, cards, gaps, warnings, sheets)
    _periods(analysis, table, gaps, warnings, sheets, charts)
    _categories(table, picked.get("category") or "", amount_column, gaps, warnings, sheets, charts)
    if gaps:
        sheets.append(
            {
                "name": "محدودیت‌ها",
                "rows": [["شاخص", "وضعیت", "ستون"]] + [[name, "قابل محاسبه نیست", column] for name, column in gaps],
            }
        )
    sheets.insert(
        0,
        {
            "name": "شاخص‌ها",
            "rows": [["شاخص", "مقدار", "واحد", "برچسب"]]
            + [[card["label"], card["value"], card["unit"], "محاسبه"] for card in cards],
        },
    )
    sheets.append(
        {
            "name": "درباره این خروجی",
            "rows": [
                ["موضوع", "وضعیت"],
                ["فایل اصلی", "دست نخورده است"],
                ["اعداد داشبورد", "با محاسبه محصول نوشته شده‌اند"],
            ],
        },
    )
    template = "مجموع فروش {total} و میانگین {mean} است."
    if "customer_count" in metrics:
        template += " تعداد مشتری {customer_count} است."
    if "top_product" in metrics:
        template += " پرفروش‌ترین محصول {top_product} است."
    elif "tie_products" in metrics:
        template += " بیشترین فروش برای {tie_products} محصول مساوی است."
    if "top_city" in metrics:
        template += " پرفروش‌ترین شهر {top_city} است."
    elif "tie_cities" in metrics:
        template += " بیشترین فروش برای {tie_cities} شهر مساوی است."
    return {
        "blocked": None,
        "summary": render(template, metrics),
        "metrics": metrics,
        "warnings": warnings,
        "cards": cards,
        "charts": charts,
        "sheets": sheets,
        "filename": "داشبورد.xlsx",
    }


def _customers(table, column: str, metrics, cards, gaps, warnings) -> None:
    if not column:
        gaps.append(("تعداد مشتری", "مشتری"))
        warnings.append("تعداد مشتری قابل محاسبه نیست. ستون مشتری نیست.")
        return
    keys = []
    for row in table["rows"]:
        parsed = _label(row.get(column))
        if parsed is None:
            continue
        key, _label_text = parsed
        if key not in keys:
            keys.append(key)
    if not keys:
        gaps.append(("تعداد مشتری", "مشتری"))
        warnings.append("تعداد مشتری قابل محاسبه نیست. ستون مشتری نیست.")
        return
    metrics["customer_count"] = str(len(keys))
    cards.append(_card("customer_count", "تعداد مشتری", metrics["customer_count"], "تعداد"))


def _cities(analysis, metrics, cards, gaps, warnings, sheets) -> None:
    ranked = _ranked(analysis["cities"])
    if not analysis["city_columns"] or not ranked:
        gaps.append(("پرفروش‌ترین شهر", "شهر"))
        warnings.append("پرفروش‌ترین شهر قابل محاسبه نیست. ستون شهر نیست.")
        return
    _crown(ranked, "city", "پرفروش‌ترین شهر", "شهر", metrics, cards, warnings)
    sheets.append(_sum_sheet("شهرها", "شهر", ranked))


def _periods(analysis, table, gaps, warnings, sheets, charts) -> None:
    periods = analysis["periods"]
    if not analysis["date_columns"] or not periods:
        gaps.append(("روند ماهانه", "تاریخ"))
        warnings.append("روند ماهانه قابل محاسبه نیست. ستون تاریخ نیست.")
        return
    points = [{"category": item["label"], "value": plain(item["amount"])} for item in periods]
    spec = make_spec("line", "روند ماهانه", analysis["date_columns"][0], points, "مبلغ", table["sheet"])
    charts.append(spec)
    sheets.append(sheet_for(spec, "روند"))


def _categories(table, column: str, amount_column: str, gaps, warnings, sheets, charts) -> None:
    if not column:
        gaps.append(("فروش دسته‌بندی", "دسته‌بندی"))
        warnings.append("فروش دسته‌بندی قابل محاسبه نیست. ستون دسته‌بندی نیست.")
        return
    ranked = _ranked(_manual_groups(table, column, amount_column))
    if not ranked:
        gaps.append(("فروش دسته‌بندی", "دسته‌بندی"))
        warnings.append("فروش دسته‌بندی قابل محاسبه نیست. ستون دسته‌بندی نیست.")
        return
    points = [{"category": item["label"], "value": plain(item["amount"])} for item in ranked]
    spec = make_spec("column", "فروش دسته‌بندی", column, points, "مبلغ", table["sheet"])
    charts.append(spec)
    sheets.append(sheet_for(spec, "دسته‌ها"))


def _product(table, column: str, amount_column: str, metrics, cards, gaps, warnings, sheets) -> None:
    title = "پرفروش‌ترین محصول"
    if not column:
        gaps.append((title, "محصول"))
        warnings.append("پرفروش‌ترین محصول قابل محاسبه نیست. ستون محصول نیست.")
        return
    ranked = _ranked(_manual_groups(table, column, amount_column))
    if not ranked:
        gaps.append((title, "محصول"))
        warnings.append("پرفروش‌ترین محصول قابل محاسبه نیست. ستون محصول نیست.")
        return
    _crown(ranked, "product", title, "محصول", metrics, cards, warnings)
    sheets.append(_sum_sheet("محصولات", "محصول", ranked))


def _crown(ranked, kind, title, unit, metrics, cards, warnings) -> None:
    top = ranked[0]["amount"]
    winners = [item for item in ranked if item["amount"] == top]
    if len(winners) == 1:
        key = "top_product" if kind == "product" else "top_city"
        metrics[key] = winners[0]["label"]
        cards.append(_card(key, title, metrics[key], unit))
        return
    tie_key = "tie_products" if kind == "product" else "tie_cities"
    metrics[tie_key] = str(len(winners))
    noun = "محصول" if kind == "product" else "شهر"
    warnings.append(f"بیشترین فروش برای چند {noun} مساوی است.")
    cards.append(_card(tie_key, f"{noun}های هم‌امتیاز", metrics[tie_key], "تعداد"))


def _manual_groups(table: dict, column: str, amount_column: str) -> list[dict]:
    buckets: dict[str, dict] = {}
    order: list[str] = []
    for row in table["rows"]:
        amount, bad = _amount(row.get(amount_column))
        if bad or amount is None:
            continue
        parsed = _label(row.get(column))
        if parsed is None:
            continue
        key, label = parsed
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {"key": key, "label": label, "amount": Decimal(0)}
            buckets[key] = bucket
            order.append(key)
        bucket["amount"] += amount
    return [buckets[key] for key in order]


def _ranked(groups: list[dict]) -> list[dict]:
    return sorted(groups, key=lambda item: (item["amount"], item["label"]), reverse=True)


def _sum_sheet(name: str, header: str, ranked: list[dict]) -> dict:
    rows = [[header, "مجموع"]]
    numbers = set()
    for index, item in enumerate(ranked, start=1):
        rows.append([item["label"], plain(item["amount"])])
        numbers.add((index, 1))
    return {"name": name, "rows": rows, "numbers": numbers}


def _card(name: str, label: str, value: str, unit: str) -> dict:
    return {"name": name, "label": label, "value": value, "unit": unit, "hypothesis": False}
