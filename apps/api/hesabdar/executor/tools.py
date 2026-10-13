from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal

from hesabdar.cleaning.service import CleaningService
from hesabdar.errors import AppError
from hesabdar.files.service import FileService
from hesabdar.files.workbook import write_workbook
from hesabdar.inspection.service import InspectionService
from hesabdar.messages import (
    CLEAN_SUCCEEDED,
    OPERATION_INVALID,
    PLAN_NEED_COLUMN,
    PLAN_NO_AMOUNT,
    RECONCILE_QUESTION,
)
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
