from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal

from hesabdar.analysis.engine import analyze, present, role_columns
from hesabdar.charts.spec import assert_charts, build_chart, grouping_columns
from hesabdar.cleaning.service import CleaningService
from hesabdar.dashboard.layout import category_columns, compose, customer_columns, product_columns
from hesabdar.errors import AppError
from hesabdar.files.service import FileService
from hesabdar.files.workbook import write_workbook
from hesabdar.formulas.live import assert_live_formulas, percent_formula
from hesabdar.inspection.service import InspectionService
from hesabdar.inspection.readers import read_workbook
from hesabdar.messages import (
    CLEAN_SUCCEEDED,
    OPERATION_INVALID,
    PLAN_NEED_CATEGORY,
    PLAN_NEED_CITY,
    PLAN_NEED_COLUMN,
    PLAN_NEED_CUSTOMER,
    PLAN_NEED_DATE,
    PLAN_NEED_PRODUCT,
    PLAN_NO_AMOUNT,
    PLAN_NO_CATEGORY,
    PLAN_NO_CITY,
    PLAN_NO_DATE,
    PLAN_MACRO,
    PLAN_NO_VERSION,
    PLAN_PIVOT,
    CONFIRM_REWRITE,
    MACRO_DROPPED,
    PIVOT_DROPPED,
    RECONCILE_QUESTION,
)
from hesabdar.structure.engine import apply, block_reason, build_management, merge_tables
from hesabdar.planner.explain import render
from hesabdar.reconcile.service import ReconcileService
from hesabdar.executor.sheets import amount_columns, assert_output, compare, grid, load_sheet, money

_LABELS = {"gt": "بیشتر از", "lt": "کمتر از", "gte": "حداقل", "lte": "حداکثر"}


@dataclass
class StepResult:
    summary: str | None = None
    warnings: list[str] = field(default_factory=list)
    outputs: list[dict] = field(default_factory=list)
    metrics: dict[str, str] = field(default_factory=dict)
    waiting: dict | None = None
    sheet_name: str | None = None
    cancelled: bool = False
    cards: list[dict] = field(default_factory=list)
    charts: list[dict] = field(default_factory=list)
    evaluation: str | None = None
    change: dict | None = None


class _Stopped(Exception):
    pass


class ToolRunner:
    def __init__(
        self,
        files: FileService,
        inspection: InspectionService,
        cleaning: CleaningService,
        reconcile: ReconcileService,
        stop: Callable[[str, str], bool] | None = None,
    ) -> None:
        self.files = files
        self.inspection = inspection
        self.cleaning = cleaning
        self.reconcile = reconcile
        self._stop = stop or (lambda _workspace_id, _operation_id: False)

    def run(self, workspace_id: str, step: dict, operation_id: str) -> StepResult:
        if self._stop(workspace_id, operation_id):
            return StepResult(cancelled=True)
        try:
            return self._dispatch(workspace_id, step, operation_id)
        except _Stopped:
            return StepResult(cancelled=True)

    def _dispatch(self, workspace_id: str, step: dict, operation_id: str) -> StepResult:
        tool = step["tool"]
        params = step["params"]
        if tool == "inspect":
            return self._inspect(workspace_id, params["file_id"])
        if tool == "preview":
            return self._preview(workspace_id, params["file_id"])
        if tool == "clean":
            return self._clean(workspace_id, params, operation_id)
        if tool == "filter":
            return self._filter(workspace_id, params, operation_id)
        if tool == "sort":
            return self._sort(workspace_id, params, operation_id)
        if tool == "add_column":
            return self._add_column(workspace_id, params, operation_id)
        if tool == "compute_column":
            return self._compute(workspace_id, params, operation_id)
        if tool == "reconcile":
            return self._reconcile(workspace_id, params, operation_id)
        if tool in {"aggregate", "rank", "trend", "outliers", "kpi", "report"}:
            return self._analysis(workspace_id, params, operation_id, tool)
        if tool == "chart":
            return self._chart(workspace_id, params, operation_id)
        if tool == "dashboard":
            return self._dashboard(workspace_id, params, operation_id)
        if tool == "apply_formula":
            return self._formula(workspace_id, params, operation_id)
        if tool == "create_workbook":
            return self._create_workbook(workspace_id, params, operation_id)
        if tool == "restore_version":
            return self._restore(workspace_id, params)
        if tool == "file_merge":
            return self._file_merge(workspace_id, params, operation_id)
        if tool in {
            "sheet_add",
            "sheet_delete",
            "sheet_rename",
            "sheet_move",
            "sheet_merge",
            "sheet_split",
            "file_split",
            "column_add",
            "column_delete",
            "column_move",
            "row_add",
            "row_delete",
            "format_cells",
            "freeze",
            "data_validation",
            "export",
        }:
            return self._structure(workspace_id, params, operation_id, tool)
        raise AppError("plan.unknown_tool", "این برنامه پذیرفته نشد.", 422)

    def _inspect(self, workspace_id: str, file_id: str) -> StepResult:
        report = self.inspection.inspect(workspace_id, file_id)
        metrics = {"sheet_count": str(report["sheet_count"])}
        return StepResult(summary=render("{sheet_count} برگه خوانده شد.", metrics), metrics=metrics)

    def _preview(self, workspace_id: str, file_id: str) -> StepResult:
        _meta, table = load_sheet(self.files, workspace_id, file_id)
        metrics = {"preview_rows": str(min(len(table["rows"]), 200))}
        return StepResult(
            summary=render("{preview_rows} ردیف در پیش‌نمایش است.", metrics),
            metrics=metrics,
            sheet_name=table["sheet"],
        )

    def _clean(self, workspace_id: str, params: dict, operation_id: str) -> StepResult:
        if self._stop(workspace_id, operation_id):
            raise _Stopped()
        report = self.cleaning.apply(workspace_id, params["file_id"], bool(params.get("confirm")))
        if report["status"] == "waiting_confirmation":
            return StepResult(
                waiting={
                    "question": report["message"],
                    "choices": [],
                    "pending": {"type": "clean_confirm", "file_id": params["file_id"]},
                }
            )
        if report["status"] != "succeeded":
            return StepResult(summary=report["message"])
        meta = self.files.get_file(workspace_id, params["file_id"])
        return StepResult(
            summary=CLEAN_SUCCEEDED,
            outputs=[
                {
                    "file_id": params["file_id"],
                    "version_id": report["result_version_id"],
                    "name": meta["original_name"],
                }
            ],
        )

    def _filter(self, workspace_id: str, params: dict, operation_id: str) -> StepResult:
        meta, table = load_sheet(self.files, workspace_id, params["file_id"])
        column, waiting = _choose_amount(table, params)
        if waiting:
            waiting["pending"] = {"type": "column", "step": _step("filter", params), "choices": waiting["choices"]}
            return StepResult(waiting=waiting, sheet_name=table["sheet"])
        threshold = Decimal(params["value"])
        matched = []
        invalid = 0
        for row in table["rows"]:
            amount = money(row.get(column))
            if amount is None:
                if row.get(column) not in (None, ""):
                    invalid += 1
                continue
            if compare(amount, params["op"], threshold):
                matched.append(row)
        metrics = {
            "matched_rows": str(len(matched)),
            "source_rows": str(len(table["rows"])),
            "threshold": params["value"],
            "excluded_invalid": str(invalid),
        }
        label = params.get("label") or _LABELS[params["op"]]
        summary = render(
            "{matched_rows} ردیف از {source_rows} ردیف مبلغشان " + label + " {threshold} بود.",
            metrics,
        )
        warnings = []
        if invalid:
            warnings.append(render("{excluded_invalid} مبلغ نامعتبر از فیلتر کنار گذاشته شد.", metrics))
        stored = self._save(workspace_id, meta, "فیلتر.xlsx", grid(table, matched), len(matched), operation_id, "filtered", "فیلتر")
        return StepResult(summary=summary, warnings=warnings, outputs=[stored], metrics=metrics, sheet_name=table["sheet"])

    def _sort(self, workspace_id: str, params: dict, operation_id: str) -> StepResult:
        meta, table = load_sheet(self.files, workspace_id, params["file_id"])
        column, waiting = _choose_amount(table, params)
        if waiting:
            waiting["pending"] = {"type": "column", "step": _step("sort", params), "choices": waiting["choices"]}
            return StepResult(waiting=waiting, sheet_name=table["sheet"])
        decorated = []
        for index, row in enumerate(table["rows"]):
            decorated.append((index, money(row.get(column)), row))
        decorated.sort(key=lambda item: (item[1] is None, Decimal(0) if item[1] is None else -item[1], item[0]))
        rows = [item[2] for item in decorated]
        metrics = {"source_rows": str(len(rows))}
        summary = render("{source_rows} ردیف بر اساس مبلغ از بزرگ به کوچک مرتب شدند.", metrics)
        stored = self._save(workspace_id, meta, "مرتب‌سازی.xlsx", grid(table, rows), len(rows), operation_id, "sorted", "مرتب‌سازی")
        return StepResult(summary=summary, outputs=[stored], metrics=metrics, sheet_name=table["sheet"])

    def _add_column(self, workspace_id: str, params: dict, operation_id: str) -> StepResult:
        meta, table = load_sheet(self.files, workspace_id, params["file_id"])
        blanks = [None for _ in table["rows"]]
        metrics = {"source_rows": str(len(table["rows"]))}
        summary = render("{source_rows} ردیف ماند و ستون جدید خالی اضافه شد.", metrics)
        stored = self._save(
            workspace_id,
            meta,
            "ستون جدید.xlsx",
            grid(table, table["rows"], (params["name"], blanks)),
            len(table["rows"]),
            operation_id,
            "column_added",
            "ستون جدید",
            header_name=params["name"],
        )
        return StepResult(summary=summary, outputs=[stored], metrics=metrics, sheet_name=table["sheet"])

    def _compute(self, workspace_id: str, params: dict, operation_id: str) -> StepResult:
        meta, table = load_sheet(self.files, workspace_id, params["file_id"])
        columns = amount_columns(table)
        if len(columns) != 2:
            return StepResult(
                waiting={
                    "question": PLAN_NEED_COLUMN if columns else PLAN_NO_AMOUNT,
                    "choices": columns[:20],
                    "pending": None,
                }
            )
        base_name, other_name = columns
        values = []
        filled = zero = invalid = 0
        for row in table["rows"]:
            base = money(row.get(base_name))
            other = money(row.get(other_name))
            if base is None or other is None:
                values.append(None)
                invalid += 1
            elif base == 0:
                values.append(None)
                zero += 1
            else:
                percent = (abs(other - base) / abs(base)) * Decimal(100)
                rendered = format(percent.quantize(Decimal("0.0001")), "f")
                if "." in rendered:
                    rendered = rendered.rstrip("0").rstrip(".")
                values.append(rendered)
                filled += 1
        metrics = {"filled": str(filled), "zero_base": str(zero), "invalid": str(invalid)}
        summary = render("ستون درصد اختلاف برای {filled} ردیف محاسبه شد.", metrics)
        warnings = []
        if zero:
            warnings.append(render("{zero_base} ردیف مبنای صفر داشت و درصد نگرفت.", metrics))
        stored = self._save(
            workspace_id,
            meta,
            "محاسبه.xlsx",
            grid(table, table["rows"], (params["name"], values)),
            len(table["rows"]),
            operation_id,
            "computed",
            "درصد اختلاف",
            header_name=params["name"],
        )
        return StepResult(summary=summary, warnings=warnings, outputs=[stored], metrics=metrics, sheet_name=table["sheet"])

    def _reconcile(self, workspace_id: str, params: dict, operation_id: str) -> StepResult:
        if self._stop(workspace_id, operation_id):
            raise _Stopped()
        report = self.reconcile.apply(
            workspace_id,
            params["left_file_id"],
            params["right_file_id"],
            list(params.get("key_columns") or []),
        )
        if report["status"] == "waiting_confirmation":
            return StepResult(
                waiting={
                    "question": report.get("question") or RECONCILE_QUESTION,
                    "choices": report.get("key_choices") or [],
                    "pending": {
                        "type": "reconcile_key",
                        "left_file_id": params["left_file_id"],
                        "right_file_id": params["right_file_id"],
                        "choices": report.get("key_choices") or [],
                    },
                }
            )
        if report["status"] != "succeeded" or not report.get("result_file_id"):
            raise AppError("output.invalid", OPERATION_INVALID, 422)
        metrics = {name: str(report["summary"][name]) for name in ("full_match", "value_mismatch", "only_left", "only_right", "ambiguous")}
        summary = render(
            "منطبق {full_match}، مغایر {value_mismatch}، فقط فایل اول {only_left}، فقط فایل دوم {only_right}، مشکوک {ambiguous}.",
            metrics,
        )
        return StepResult(
            summary=summary,
            outputs=[
                {
                    "file_id": report["result_file_id"],
                    "version_id": report["result_version_id"],
                    "name": report["result_name"],
                }
            ],
            metrics=metrics,
        )

    def _analysis(self, workspace_id: str, params: dict, operation_id: str, tool: str) -> StepResult:
        meta, table = load_sheet(self.files, workspace_id, params["file_id"])
        column, waiting = _choose_amount(table, params)
        if waiting:
            waiting["pending"] = {"type": "column", "field": "column", "step": _step(tool, params), "choices": waiting["choices"]}
            return StepResult(waiting=waiting, sheet_name=table["sheet"])
        for role, field_name, question in (
            ("city", "city", PLAN_NEED_CITY),
            ("date", "date", PLAN_NEED_DATE),
        ):
            if tool == "rank" and role == "date":
                continue
            if tool == "trend" and role == "city":
                continue
            if tool in {"aggregate", "kpi", "outliers"}:
                continue
            chosen, waiting = _choose_role(table, params, tool, role, field_name, question)
            if waiting:
                return StepResult(waiting=waiting, sheet_name=table["sheet"])
            if chosen:
                table = _pin_role(table, role, chosen)
        view = present(analyze(table, column), tool)
        if view["blocked"]:
            return StepResult(
                waiting={"question": view["blocked"], "choices": [], "pending": None},
                sheet_name=table["sheet"],
            )
        stored = self._save_analysis(workspace_id, meta, view, operation_id)
        return StepResult(
            summary=view["summary"],
            warnings=view["warnings"],
            outputs=[stored],
            metrics=view["metrics"],
            cards=view["cards"],
            sheet_name=table["sheet"],
        )

    def _save_analysis(self, workspace_id: str, meta: dict, view: dict, operation_id: str) -> dict:
        if self._stop(workspace_id, operation_id):
            raise _Stopped()
        data = write_workbook(view["sheets"], "xlsx")
        _assert_analysis(data, view["cards"], [sheet["name"] for sheet in view["sheets"]])
        if self._stop(workspace_id, operation_id):
            raise _Stopped()
        stored = self.files.add_output_file(
            workspace_id,
            view["filename"],
            data,
            kind="analysis",
            note="تحلیل",
            parent_version_id=meta["current_version_id"],
            operation_id=operation_id,
            row_count=len(view["cards"]),
            sheet_count=len(view["sheets"]),
        )
        return {"file_id": stored["id"], "version_id": stored["current_version_id"], "name": stored["original_name"]}

    def _chart(self, workspace_id: str, params: dict, operation_id: str) -> StepResult:
        meta, table = load_sheet(self.files, workspace_id, params["file_id"])
        column, waiting = _choose_amount(table, params)
        if waiting:
            waiting["pending"] = {"type": "column", "field": "column", "step": _step("chart", params), "choices": waiting["choices"]}
            return StepResult(waiting=waiting, sheet_name=table["sheet"])
        chart_type = params.get("chart_type") or "column"
        title = params.get("title") or "فروش"
        category = None
        if chart_type != "scatter":
            category, waiting = _choose_named(
                table,
                params,
                "chart",
                "category",
                grouping_columns(table, params.get("category_role")),
                PLAN_NEED_CATEGORY,
                _missing_category(params.get("category_role")),
            )
            if waiting:
                return StepResult(waiting=waiting, sheet_name=table["sheet"])
        built = build_chart(table, column, chart_type, title, category, table["sheet"] or "برگه")
        if built["blocked"]:
            return StepResult(waiting={"question": built["blocked"], "choices": [], "pending": None}, sheet_name=table["sheet"])
        spec = built["spec"]
        metrics = {"point_count": str(len(spec["series"][0]["points"])), "title": spec["title"]}
        summary = render("نمودار {title} با {point_count} نقطه ساخته شد.", metrics)
        cards = [_metric("point_count", "تعداد نقطه", metrics["point_count"], "تعداد")]
        stored = self._save_rendered(
            workspace_id,
            meta,
            "نمودار.xlsx",
            [built["sheet"]],
            operation_id,
            "chart",
            "نمودار",
            None,
            [(built["sheet"]["name"], spec)],
        )
        return StepResult(
            summary=summary,
            outputs=[stored],
            metrics=metrics,
            cards=cards,
            charts=[spec],
            sheet_name=table["sheet"],
        )

    def _dashboard(self, workspace_id: str, params: dict, operation_id: str) -> StepResult:
        meta, table = load_sheet(self.files, workspace_id, params["file_id"])
        column, waiting = _choose_amount(table, params)
        if waiting:
            waiting["pending"] = {"type": "column", "field": "column", "step": _step("dashboard", params), "choices": waiting["choices"]}
            return StepResult(waiting=waiting, sheet_name=table["sheet"])
        for role, field_name, question in (("city", "city", PLAN_NEED_CITY), ("date", "date", PLAN_NEED_DATE)):
            chosen, waiting = _choose_role(table, params, "dashboard", role, field_name, question)
            if waiting:
                return StepResult(waiting=waiting, sheet_name=table["sheet"])
            if chosen:
                table = _pin_role(table, role, chosen)
        picked = {}
        for field_name, columns, question in (
            ("customer", customer_columns(table), PLAN_NEED_CUSTOMER),
            ("product", product_columns(table), PLAN_NEED_PRODUCT),
            ("category", category_columns(table), PLAN_NEED_CATEGORY),
        ):
            chosen, waiting = _choose_named(table, params, "dashboard", field_name, columns, question, "")
            if waiting:
                return StepResult(waiting=waiting, sheet_name=table["sheet"])
            picked[field_name] = chosen or ""
        view = compose(table, analyze(table, column), picked, column)
        if view["blocked"]:
            return StepResult(waiting={"question": view["blocked"], "choices": [], "pending": None}, sheet_name=table["sheet"])
        pairs = [(sheet["name"], spec) for sheet, spec in zip(_chart_sheets(view["sheets"]), view["charts"], strict=True)]
        stored = self._save_rendered(
            workspace_id,
            meta,
            view["filename"],
            view["sheets"],
            operation_id,
            "dashboard",
            "داشبورد",
            view["cards"],
            pairs,
        )
        return StepResult(
            summary=view["summary"],
            warnings=view["warnings"],
            outputs=[stored],
            metrics=view["metrics"],
            cards=view["cards"],
            charts=view["charts"],
            sheet_name=table["sheet"],
        )

    def _formula(self, workspace_id: str, params: dict, operation_id: str) -> StepResult:
        meta, table = load_sheet(self.files, workspace_id, params["file_id"])
        columns = amount_columns(table)
        if len(columns) != 2:
            return StepResult(
                waiting={
                    "question": PLAN_NEED_COLUMN if columns else PLAN_NO_AMOUNT,
                    "choices": columns[:20],
                    "pending": None,
                },
                sheet_name=table["sheet"],
            )
        base_name, other_name = columns
        base_index = table["headers"].index(base_name)
        other_index = table["headers"].index(other_name)
        new_index = len(table["headers"])
        body = [list(table["headers"]) + [params["name"]]]
        formulas: set[tuple[int, int]] = set()
        expected = []
        for offset, row in enumerate(table["rows"]):
            excel_row = offset + 2
            text = percent_formula(base_index, other_index, excel_row)
            body.append([row.get(name) for name in table["headers"]] + [text])
            formulas.add((offset + 1, new_index))
            expected.append((excel_row, new_index + 1, text))
        sheets = [
            {"name": table["sheet"] or "برگه", "rows": body, "formulas": formulas},
            {
                "name": "درباره این خروجی",
                "rows": [
                    ["موضوع", "وضعیت"],
                    ["فرمول زنده", "ارزیابی نشده"],
                    ["فایل اصلی", "دست نخورده است"],
                ],
            },
        ]
        metrics = {"formula_rows": str(len(table["rows"]))}
        summary = render("فرمول درصد اختلاف برای {formula_rows} ردیف نوشته شد. ارزیابی نشده.", metrics)
        stored = self._save_rendered(
            workspace_id,
            meta,
            "فرمول.xlsx",
            sheets,
            operation_id,
            "formula",
            "فرمول",
            None,
            [],
            expected,
        )
        return StepResult(
            summary=summary,
            warnings=["موتور اکسل این فرمول را حساب نکرده است."],
            outputs=[stored],
            metrics=metrics,
            evaluation="unchecked",
            sheet_name=table["sheet"],
        )

    def _restore(self, workspace_id: str, params: dict) -> StepResult:
        meta = self.files.get_file(workspace_id, params["file_id"])
        versions = self.files.list_versions(workspace_id, params["file_id"])
        chosen = _restore_target(versions, meta["current_version_id"], params.get("target") or "previous")
        if chosen is None:
            return StepResult(waiting={"question": PLAN_NO_VERSION, "choices": [], "pending": None})
        restored = self.files.point_at_version(workspace_id, params["file_id"], chosen["id"])
        return StepResult(
            summary="نسخه جاری به نسخه انتخاب‌شده برگشت.",
            outputs=[
                {
                    "file_id": restored["id"],
                    "version_id": restored["current_version_id"],
                    "name": restored["original_name"],
                }
            ],
            change={
                "rows_before": None,
                "columns_before": None,
                "sheets_before": None,
                "rows_after": None,
                "columns_after": None,
                "sheets_after": None,
                "sha256_before": meta["sha256"],
                "sha256_after": restored["sha256"],
            },
        )

    def _create_workbook(self, workspace_id: str, params: dict, operation_id: str) -> StepResult:
        built = build_management(params.get("text") or "")
        return self._finish_structure(workspace_id, params, operation_id, "create_workbook", built, None, [], "مدیریت فروش.xlsx")

    def _file_merge(self, workspace_id: str, params: dict, operation_id: str) -> StepResult:
        left_meta, _left_data, left = self._load_book(workspace_id, params["left_file_id"])
        right_meta, _right_data, right = self._load_book(workspace_id, params["right_file_id"])
        flags = list(dict.fromkeys([*left.workbook_flags, *right.workbook_flags]))
        tables = [sheet for sheet in (_primary(left), _primary(right)) if sheet is not None]
        built = merge_tables(tables, "فایل")
        return self._finish_structure(
            workspace_id,
            params,
            operation_id,
            "file_merge",
            built,
            left_meta,
            flags,
            "ادغام فایل.xlsx",
        )

    def _structure(self, workspace_id: str, params: dict, operation_id: str, tool: str) -> StepResult:
        meta, _data, read = self._load_book(workspace_id, params["file_id"])
        built = apply(tool, _views(read), params.get("text") or "")
        return self._finish_structure(
            workspace_id,
            params,
            operation_id,
            tool,
            built,
            meta,
            read.workbook_flags,
            _OUTPUT_NAMES.get(tool, "ساختار.xlsx"),
        )

    def _finish_structure(
        self,
        workspace_id: str,
        params: dict,
        operation_id: str,
        tool: str,
        built: dict,
        meta: dict | None,
        flags: list[str],
        filename: str,
    ) -> StepResult:
        if built.get("question"):
            return StepResult(waiting={"question": built["question"], "choices": [], "pending": None})
        reason = block_reason(flags, bool(params.get("confirm")))
        if reason:
            step = {"tool": tool, "params": dict(params), "reads": _structure_reads(params), "writes": ["result"]}
            return StepResult(
                waiting={
                    "question": PLAN_MACRO if reason == "macro" else PLAN_PIVOT,
                    "choices": [CONFIRM_REWRITE],
                    "pending": {"type": "column", "field": "confirm", "step": step, "choices": [CONFIRM_REWRITE]},
                }
            )
        warnings = list(built.get("warnings") or [])
        if params.get("confirm"):
            if "macro" in flags:
                warnings.append(MACRO_DROPPED)
            if "pivot_table" in flags:
                warnings.append(PIVOT_DROPPED)
        parent = meta["current_version_id"] if meta else None
        file_format = built.get("file_format") or "xlsx"
        outputs = []
        bundles = built.get("files")
        if bundles:
            for bundle in bundles:
                outputs.append(
                    self._store_new(
                        workspace_id,
                        bundle["name"],
                        bundle["sheets"],
                        operation_id,
                        tool,
                        parent,
                        file_format,
                    )
                )
        else:
            outputs.append(
                self._store_new(
                    workspace_id,
                    built.get("filename") or filename,
                    built["sheets"],
                    operation_id,
                    tool,
                    parent,
                    file_format,
                )
            )
        return StepResult(summary=built.get("summary"), warnings=warnings, outputs=outputs, metrics=built.get("metrics") or {})

    def _load_book(self, workspace_id: str, file_id: str):
        meta = self.files.get_file(workspace_id, file_id)
        _record, data = self.files.read_version(workspace_id, meta["current_version_id"])
        return meta, data, read_workbook(data, meta["format"], meta["original_name"])

    def _store_new(
        self,
        workspace_id: str,
        name: str,
        sheets: list[dict],
        operation_id: str,
        kind: str,
        parent: str | None,
        file_format: str,
    ) -> dict:
        if self._stop(workspace_id, operation_id):
            raise _Stopped()
        data = write_workbook(sheets, file_format)
        if file_format == "xlsx":
            try:
                read = read_workbook(data, "xlsx", name)
            except AppError:
                raise AppError("output.invalid", OPERATION_INVALID, 422) from None
            if [sheet.name for sheet in read.sheets] != [sheet["name"][:31] for sheet in sheets]:
                raise AppError("output.invalid", OPERATION_INVALID, 422)
        if self._stop(workspace_id, operation_id):
            raise _Stopped()
        stored = self.files.add_output_file(
            workspace_id,
            name,
            data,
            kind=kind,
            note=name,
            parent_version_id=parent,
            operation_id=operation_id,
            row_count=sum(max(len(sheet["rows"]) - 1, 0) for sheet in sheets),
            sheet_count=len(sheets),
            file_format=file_format,
        )
        return {"file_id": stored["id"], "version_id": stored["current_version_id"], "name": stored["original_name"]}

    def _save_rendered(
        self,
        workspace_id: str,
        meta: dict,
        name: str,
        sheets: list[dict],
        operation_id: str,
        kind: str,
        note: str,
        cards: list[dict] | None,
        chart_pairs: list[tuple[str, dict]],
        formulas: list[tuple[int, int, str]] | None = None,
    ) -> dict:
        if self._stop(workspace_id, operation_id):
            raise _Stopped()
        data = write_workbook(sheets, "xlsx")
        if chart_pairs:
            assert_charts(data, chart_pairs)
        if cards:
            _assert_metric_sheet(data, cards)
        if formulas:
            assert_live_formulas(data, formulas)
        if self._stop(workspace_id, operation_id):
            raise _Stopped()
        stored = self.files.add_output_file(
            workspace_id,
            name,
            data,
            kind=kind,
            note=note,
            parent_version_id=meta["current_version_id"],
            operation_id=operation_id,
            row_count=max(len(sheets[0]["rows"]) - 1, 0),
            sheet_count=len(sheets),
        )
        return {"file_id": stored["id"], "version_id": stored["current_version_id"], "name": stored["original_name"]}

    def _save(
        self,
        workspace_id: str,
        meta: dict,
        name: str,
        sheets: list[dict],
        data_rows: int,
        operation_id: str,
        kind: str,
        note: str,
        header_name: str | None = None,
    ) -> dict:
        if self._stop(workspace_id, operation_id):
            raise _Stopped()
        data = write_workbook(sheets, "xlsx")
        assert_output(data, data_rows, header_name)
        if self._stop(workspace_id, operation_id):
            raise _Stopped()
        stored = self.files.add_output_file(
            workspace_id,
            name,
            data,
            kind=kind,
            note=note,
            parent_version_id=meta["current_version_id"],
            operation_id=operation_id,
            row_count=data_rows,
            sheet_count=1,
        )
        return {"file_id": stored["id"], "version_id": stored["current_version_id"], "name": stored["original_name"]}


_OUTPUT_NAMES = {
    "sheet_merge": "ادغام.xlsx",
    "sheet_split": "تقسیم برگه.xlsx",
    "file_split": "تقسیم.xlsx",
    "sheet_add": "ساختار.xlsx",
    "sheet_delete": "ساختار.xlsx",
    "sheet_rename": "ساختار.xlsx",
    "sheet_move": "ساختار.xlsx",
    "column_add": "ساختار.xlsx",
    "column_delete": "ساختار.xlsx",
    "column_move": "ساختار.xlsx",
    "row_add": "ساختار.xlsx",
    "row_delete": "ساختار.xlsx",
    "format_cells": "ساختار.xlsx",
    "freeze": "ساختار.xlsx",
    "data_validation": "ساختار.xlsx",
    "export": "خروجی.csv",
}


def _restore_target(versions: list[dict], current_id: str, target: str) -> dict | None:
    if target == "original":
        chosen = next((item for item in versions if item["kind"] == "original"), None)
    else:
        ids = [item["id"] for item in versions]
        if current_id not in ids:
            return None
        index = ids.index(current_id)
        chosen = versions[index - 1] if index > 0 else None
    if chosen is None or chosen["id"] == current_id:
        return None
    return chosen


def _views(read) -> list[dict]:
    sheets = []
    for sheet in read.sheets:
        if not sheet.rows:
            continue
        rows = []
        formulas = set()
        for row_index, row in enumerate(sheet.rows):
            values = []
            for column_index, cell in enumerate(row):
                values.append(cell.raw)
                if cell.formula:
                    formulas.add((row_index, column_index))
            rows.append(values)
        sheets.append({"name": sheet.name, "rows": rows, "formulas": formulas})
    return sheets


def _primary(read) -> dict | None:
    sheets = _views(read)
    if not sheets:
        return None
    return max(sheets, key=lambda sheet: max(len(sheet["rows"]) - 1, 0))


def _structure_reads(params: dict) -> list[str]:
    found = []
    for key in ("file_id", "left_file_id", "right_file_id"):
        value = params.get(key)
        if value and value not in found:
            found.append(value)
    return found


def _choose_amount(table: dict, params: dict) -> tuple[str | None, dict | None]:
    columns = amount_columns(table)
    chosen = params.get("column")
    if chosen:
        if chosen not in table["headers"]:
            raise AppError("request.invalid", "درخواست نامعتبر است.", 400)
        return chosen, None
    if len(columns) == 1:
        return columns[0], None
    if not columns:
        return None, {"question": PLAN_NO_AMOUNT, "choices": [], "pending": None}
    return None, {"question": PLAN_NEED_COLUMN, "choices": columns[:20], "pending": None}


def _step(tool: str, params: dict) -> dict:
    return {"tool": tool, "params": dict(params), "reads": [params["file_id"]], "writes": ["result"]}


def _choose_role(table: dict, params: dict, tool: str, role: str, field_name: str, question: str):
    columns = role_columns(table, role)
    chosen = params.get(field_name)
    if chosen:
        if chosen not in table["headers"]:
            raise AppError("request.invalid", "درخواست نامعتبر است.", 400)
        return chosen, None
    if len(columns) <= 1:
        return columns[0] if columns else None, None
    return None, {
        "question": question,
        "choices": columns[:20],
        "pending": {"type": "column", "field": field_name, "step": _step(tool, params), "choices": columns[:20]},
    }


def _pin_role(table: dict, role: str, chosen: str) -> dict:
    roles = dict(table["roles"])
    for name in role_columns(table, role):
        if name != chosen:
            roles[name] = None
    return {**table, "roles": roles}


def _assert_analysis(data: bytes, cards: list[dict], names: list[str]) -> None:
    try:
        read = read_workbook(data, "xlsx", "گزارش.xlsx")
    except AppError:
        raise AppError("output.invalid", OPERATION_INVALID, 422) from None
    found = [sheet.name for sheet in read.sheets]
    if found != names or not found:
        raise AppError("output.invalid", OPERATION_INVALID, 422)
    if not cards:
        return
    metric_sheet = next(sheet for sheet in read.sheets if sheet.name == "شاخص‌ها")
    values = []
    for row in metric_sheet.rows[1:]:
        cell = row[1] if len(row) > 1 else None
        values.append(None if cell is None else cell.raw)
    if values != [card["value"] for card in cards]:
        raise AppError("output.invalid", OPERATION_INVALID, 422)


def _choose_named(table: dict, params: dict, tool: str, field: str, columns: list[str], question: str, missing: str):
    chosen = params.get(field)
    if chosen:
        if chosen not in table["headers"]:
            raise AppError("request.invalid", "درخواست نامعتبر است.", 400)
        return chosen, None
    if len(columns) == 1:
        return columns[0], None
    if not columns:
        if missing:
            return None, {"question": missing, "choices": [], "pending": None}
        return None, None
    return None, {
        "question": question,
        "choices": columns[:20],
        "pending": {"type": "column", "field": field, "step": _step(tool, params), "choices": columns[:20]},
    }


def _missing_category(role: str | None) -> str:
    if role == "date":
        return PLAN_NO_DATE
    if role == "city":
        return PLAN_NO_CITY
    return PLAN_NO_CATEGORY


def _metric(name: str, label: str, value: str, unit: str) -> dict:
    return {"name": name, "label": label, "value": value, "unit": unit, "hypothesis": False}


def _chart_sheets(sheets: list[dict]) -> list[dict]:
    return [sheet for sheet in sheets if sheet.get("chart")]


def _assert_metric_sheet(data: bytes, cards: list[dict]) -> None:
    try:
        read = read_workbook(data, "xlsx", "گزارش.xlsx")
    except AppError:
        raise AppError("output.invalid", OPERATION_INVALID, 422) from None
    metric_sheet = next((sheet for sheet in read.sheets if sheet.name == "شاخص‌ها"), None)
    if metric_sheet is None:
        raise AppError("output.invalid", OPERATION_INVALID, 422)
    values = []
    for row in metric_sheet.rows[1:]:
        cell = row[1] if len(row) > 1 else None
        values.append(None if cell is None else cell.raw)
    if values != [card["value"] for card in cards]:
        raise AppError("output.invalid", OPERATION_INVALID, 422)
