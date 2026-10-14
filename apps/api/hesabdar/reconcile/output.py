from __future__ import annotations

SHEET_NAMES = [
    "خلاصه",
    "منطبق",
    "مغایر",
    "فقط فایل اول",
    "فقط فایل دوم",
    "مشکوک",
    "درباره این خروجی",
]

STATUS_SHEET = {
    "full_match": "منطبق",
    "value_mismatch": "مغایر",
    "only_left": "فقط فایل اول",
    "only_right": "فقط فایل دوم",
    "ambiguous": "مشکوک",
}

SUMMARY_LABELS = {
    "full_match": "منطبق",
    "value_mismatch": "مغایر",
    "only_left": "فقط فایل اول",
    "only_right": "فقط فایل دوم",
    "ambiguous": "مشکوک",
}

DETAIL_HEADER = [
    "کلید چپ",
    "کلید راست",
    "نام چپ",
    "نام راست",
    "مبلغ چپ",
    "مبلغ راست",
    "اختلاف مبلغ",
    "نسبت اختلاف",
    "اطمینان",
    "علت",
]


def build_sheets(report: dict) -> list[dict]:
    summary = report["summary"]
    validation = report["validation"]
    key_text = "، ".join(report["key_columns"])
    summary_rows = [
        ["موضوع", "مقدار"],
        ["منطبق", str(summary["full_match"])],
        ["مغایر", str(summary["value_mismatch"])],
        ["فقط فایل اول", str(summary["only_left"])],
        ["فقط فایل دوم", str(summary["only_right"])],
        ["مشکوک", str(summary["ambiguous"])],
        ["ردیف چپ", str(validation["left_rows"])],
        ["ردیف راست", str(validation["right_rows"])],
        ["جمع مبلغ چپ", validation["left_amount"] or "0"],
        ["جمع مبلغ راست", validation["right_amount"] or "0"],
        ["کلید", key_text],
        ["تصمیم کلید", report["key_decision"]],
    ]
    grouped = {name: [] for name in STATUS_SHEET.values()}
    for row in report["rows"]:
        grouped[STATUS_SHEET[row["status"]]].append(_detail(row))
    sheets = [{"name": "خلاصه", "rows": summary_rows}]
    for name in SHEET_NAMES[1:-1]:
        sheets.append({"name": name, "rows": [DETAIL_HEADER, *grouped[name]]})
    sheets.append(
        {
            "name": "درباره این خروجی",
            "rows": [
                ["موضوع", "توضیح"],
                ["این فایل", "خروجی مغایرت است. فایل‌های اصلی عوض نشده‌اند."],
                ["کلید", key_text],
                ["هویت شمارش", "هر ردیف ورودی دقیقاً در یک دسته است."],
                ["نسبت اختلاف", "اگر مبلغ مبنا صفر یا نامعتبر باشد، نسبت تهی است و علت در ردیف آمده است."],
                ["مشکوک", "شباهت نام بدون شناسه مشترک قطعی نیست."],
            ],
        }
    )
    return sheets


def _detail(row: dict) -> list:
    return [
        row.get("key_left") or None,
        row.get("key_right") or None,
        row.get("name_left"),
        row.get("name_right"),
        row.get("amount_left"),
        row.get("amount_right"),
        row.get("amount_delta"),
        row.get("amount_delta_ratio"),
        _confidence(row.get("confidence")),
        row.get("reason") or None,
    ]


def _confidence(value) -> str:
    if value is None:
        return "0"
    if isinstance(value, float):
        rendered = format(value, "f").rstrip("0").rstrip(".")
        return rendered or "0"
    return str(value)
