from __future__ import annotations

import copy
import json
import logging
import threading
import uuid
from datetime import datetime, timezone

from hesabdar.cleaning.service import CleaningService
from hesabdar.config import Settings
from hesabdar.db import Database
from hesabdar.errors import AppError
from hesabdar.executor.tools import ToolRunner
from hesabdar.files.service import FileService
from hesabdar.inspection.service import InspectionService
from hesabdar.messages import (
    INTERNAL,
    JOB_CANCELLED,
    OPERATION_INVALID,
    OPERATION_NOT_FOUND,
    PLAN_NEED_REPORT,
    REQUEST_INVALID,
)
from hesabdar.planner.explain import consistent
from hesabdar.planner.llm import llm_status
from hesabdar.planner.rules import build_plan, repeat_period
from hesabdar.planner.validate import validate_plan
from hesabdar.reconcile.service import ReconcileService

logger = logging.getLogger("hesabdar.executor")

_GUARD = threading.Lock()
_LOCKS: dict[str, threading.Lock] = {}
_EMPTY_FOCUS = {
    "file_ids": [],
    "sheet_name": None,
    "columns": [],
    "last_plan_id": None,
    "last_result_version_id": None,
    "last_period_label": None,
}
_DONE = {
    "filter": "فیلتر انجام شد",
    "sort": "مرتب‌سازی انجام شد",
    "add_column": "ستون اضافه شد",
    "compute_column": "محاسبه انجام شد",
    "reconcile": "مغایرت انجام شد",
    "clean": "پاک‌سازی انجام شد",
    "inspect": "بررسی انجام شد",
    "preview": "پیش‌نمایش آماده است",
}
_BUSY = {
    "filter": "در حال فیلتر",
    "sort": "در حال مرتب‌سازی",
    "add_column": "در حال افزودن ستون",
    "compute_column": "در حال محاسبه",
    "reconcile": "در حال مغایرت",
    "clean": "در حال پاک‌سازی",
    "inspect": "در حال بررسی",
    "preview": "در حال پیش‌نمایش",
}
_PERIOD_NOTE = " این نتیجه برای مهر است."


class OperationService:
    def __init__(
        self,
        settings: Settings,
        files: FileService,
        database: Database,
        inspection: InspectionService,
        cleaning: CleaningService,
        reconcile: ReconcileService,
    ) -> None:
        self.settings = settings
        self.files = files
        self.database = database
        self.runner = ToolRunner(files, inspection, cleaning, reconcile, stop=self._is_cancelled)
        self._pause_next = False
        self._gate_lock = threading.Lock()
        self._gates: dict[str, threading.Event] = {}
        self._entered: dict[str, threading.Event] = {}
        self._workers: dict[str, threading.Thread] = {}

    def arm_pause(self) -> None:
        self._pause_next = True

    def release(self) -> None:
        self._pause_next = False
        with self._gate_lock:
            gates = list(self._gates.values())
            workers = list(self._workers.values())
        for gate in gates:
            gate.set()
        for worker in workers:
            if worker is not threading.current_thread():
                worker.join(timeout=30)

    def submit(self, workspace_id: str, text: str, file_ids: list[str] | None) -> dict:
        with _workspace_lock(workspace_id):
            self.files.get_workspace(workspace_id)
            running = self._find_running(workspace_id)
            if running is not None:
                return _public(running)
            chosen = self._existing_files(workspace_id, file_ids)
            if chosen:
                self._save_focus(workspace_id, {**self._focus(workspace_id), "file_ids": chosen})
            elif not file_ids:
                chosen = list(self._focus(workspace_id).get("file_ids") or [])
                self._existing_files(workspace_id, chosen)
            period = repeat_period(text)
            if period:
                try:
                    plan = self._period_plan(workspace_id, text, period)
                except AppError as exc:
                    return self._save(workspace_id, self._failed(workspace_id, exc))
                if plan is None:
                    return self._ask_report(workspace_id, text)
            else:
                try:
                    plan = build_plan(text, workspace_id, chosen)
                    validate_plan(plan)
                except AppError as exc:
                    return self._save(workspace_id, self._failed(workspace_id, exc))
                if plan["ambiguities"]:
                    return self._save(workspace_id, self._waiting(workspace_id, plan, plan["ambiguities"][0]))
            operation_id, paused, worker = self._start(workspace_id, plan, plan["steps"])
        return self._join_or_running(workspace_id, operation_id, paused, worker)

    def confirm(self, workspace_id: str, operation_id: str, key_columns: list[str], column: str | None) -> dict:
        with _workspace_lock(workspace_id):
            record = self._load(workspace_id, operation_id)
            pending = record.get("pending")
            if record["status"] == "succeeded" or not pending:
                return _public(record)
            if pending["type"] == "reconcile_key":
                if not key_columns:
                    return _public(record)
                _check_names(key_columns)
                if pending["choices"] and any(name not in pending["choices"] for name in key_columns):
                    raise AppError("request.invalid", REQUEST_INVALID, 400)
                step = {
                    "tool": "reconcile",
                    "params": {
                        "left_file_id": pending["left_file_id"],
                        "right_file_id": pending["right_file_id"],
                        "key_columns": key_columns,
                    },
                    "reads": [pending["left_file_id"], pending["right_file_id"]],
                    "writes": ["result"],
                }
                plan = record["plan"]
                plan["steps"] = [step]
                plan["requires_confirmation"] = False
                return self._execute(workspace_id, plan, [step], operation_id=record["id"])
            if pending["type"] == "clean_confirm":
                step = {
                    "tool": "clean",
                    "params": {"file_id": pending["file_id"], "confirm": True},
                    "reads": [pending["file_id"]],
                    "writes": ["result"],
                }
                return self._execute(workspace_id, record["plan"], [step], operation_id=record["id"])
            if pending["type"] == "column":
                if not column or column not in pending["choices"]:
                    raise AppError("request.invalid", REQUEST_INVALID, 400)
                step = pending["step"]
                step["params"]["column"] = column
                return self._execute(workspace_id, record["plan"], [step], operation_id=record["id"])
            return _public(record)

    def cancel(self, workspace_id: str, operation_id: str) -> dict:
        with _workspace_lock(workspace_id):
            self.files.get_workspace(workspace_id)
            record = self._load(workspace_id, operation_id)
            if record["status"] != "running":
                return _public(record)
            record["status"] = "cancelled"
            record["summary"] = JOB_CANCELLED
            record["outputs"] = []
            record["error"] = None
            record["warnings"] = []
            record["progress_label"] = "لغو شد"
            record["finished_at"] = _now()
            saved = self._save(workspace_id, record)
        self._wake(operation_id)
        return saved

    def get(self, workspace_id: str, operation_id: str) -> dict:
        self.files.get_workspace(workspace_id)
        return _public(self._load(workspace_id, operation_id))

    def _execute(self, workspace_id: str, plan: dict, steps: list[dict], operation_id: str | None = None) -> dict:
        operation_id = operation_id or plan["id"]
        summary = None
        warnings: list[str] = []
        outputs: list[dict] = []
        sheet_name = None
        try:
            validate_plan({"steps": steps})
            for index, step in enumerate(steps):
                if self._is_cancelled(workspace_id, operation_id):
                    return self.get(workspace_id, operation_id)
                self._touch(workspace_id, operation_id, index, _BUSY.get(step["tool"], "در حال اجرا"))
                result = self.runner.run(workspace_id, step, operation_id)
                if result.cancelled or self._is_cancelled(workspace_id, operation_id):
                    return self.get(workspace_id, operation_id)
                for warning in result.warnings:
                    if not consistent(warning, result.metrics):
                        raise AppError("output.invalid", OPERATION_INVALID, 422)
                if result.summary and not consistent(result.summary, result.metrics):
                    raise AppError("output.invalid", OPERATION_INVALID, 422)
                if result.waiting:
                    ambiguity = {
                        "code": "plan.ambiguous",
                        "question": result.waiting["question"],
                        "choices": result.waiting["choices"],
                    }
                    plan["ambiguities"] = [ambiguity]
                    plan["requires_confirmation"] = True
                    return self._save(
                        workspace_id,
                        self._waiting(workspace_id, plan, ambiguity, operation_id, result.waiting.get("pending")),
                    )
                if step["tool"] != "inspect":
                    summary = result.summary
                elif summary is None:
                    summary = result.summary
                warnings.extend(result.warnings)
                outputs.extend(result.outputs)
                sheet_name = result.sheet_name or sheet_name
        except AppError as exc:
            if exc.status_code in {400, 404}:
                raise
            return self._save(workspace_id, self._failed(workspace_id, exc, operation_id, plan))
        except Exception:
            logger.exception("operation failed")
            return self._save(
                workspace_id,
                self._failed(workspace_id, AppError("internal", INTERNAL, 500), operation_id, plan),
            )
        if self._is_cancelled(workspace_id, operation_id):
            return self.get(workspace_id, operation_id)
        if summary and plan.get("period") == "مهر":
            summary = summary + _PERIOD_NOTE
        record = self._load_or_base(workspace_id, operation_id, plan)
        record["status"] = "succeeded"
        record["progress_current"] = len(steps)
        record["progress_total"] = len(steps)
        record["progress_label"] = _DONE.get(plan.get("goal") or steps[-1]["tool"], "انجام شد")
        record["summary"] = summary
        record["warnings"] = warnings
        record["outputs"] = outputs
        record["error"] = None
        record["pending"] = None
        record["finished_at"] = _now()
        saved = self._save(workspace_id, record)
        if saved["status"] != "succeeded":
            return saved
        self._save_focus(
            workspace_id,
            {
                "file_ids": _input_files(plan, steps),
                "sheet_name": sheet_name,
                "columns": [],
                "last_plan_id": operation_id,
                "last_result_version_id": outputs[-1]["version_id"] if outputs else None,
                "last_period_label": plan.get("period"),
            },
        )
        return saved

    def _start(self, workspace_id: str, plan: dict, steps: list[dict]) -> tuple[str, bool, threading.Thread]:
        operation_id = plan["id"]
        record = self._base(workspace_id, operation_id, plan)
        record["progress_current"] = 0
        record["progress_total"] = len(steps)
        record["progress_label"] = "در حال اجرا"
        record["outputs"] = []
        self._save(workspace_id, record)
        gate = threading.Event()
        entered = threading.Event()
        paused = False
        if self._pause_next:
            self._pause_next = False
            paused = True
        else:
            gate.set()
        worker = threading.Thread(
            target=self._worker,
            args=(workspace_id, plan, steps, operation_id, gate, entered),
            daemon=True,
            name=f"hesabdar-{operation_id[:8]}",
        )
        with self._gate_lock:
            self._gates[operation_id] = gate
            self._entered[operation_id] = entered
            self._workers[operation_id] = worker
        worker.start()
        return operation_id, paused, worker

    def _worker(
        self,
        workspace_id: str,
        plan: dict,
        steps: list[dict],
        operation_id: str,
        gate: threading.Event,
        entered: threading.Event,
    ) -> None:
        entered.set()
        try:
            gate.wait()
            if self._is_cancelled(workspace_id, operation_id):
                return
            self._execute(workspace_id, plan, steps, operation_id=operation_id)
        except AppError as exc:
            if not self._is_cancelled(workspace_id, operation_id):
                self._save(workspace_id, self._failed(workspace_id, exc, operation_id, plan))
        except Exception:
            logger.exception("operation failed")
            if not self._is_cancelled(workspace_id, operation_id):
                self._save(
                    workspace_id,
                    self._failed(workspace_id, AppError("internal", INTERNAL, 500), operation_id, plan),
                )

    def _join_or_running(
        self,
        workspace_id: str,
        operation_id: str,
        paused: bool,
        worker: threading.Thread,
    ) -> dict:
        entered = self._entered.get(operation_id)
        if entered is not None:
            entered.wait(timeout=10)
        gate = self._gates.get(operation_id)
        if paused and gate is not None and not gate.is_set():
            return self.get(workspace_id, operation_id)
        if worker is not threading.current_thread():
            worker.join()
        return self.get(workspace_id, operation_id)

    def _wake(self, operation_id: str) -> None:
        with self._gate_lock:
            gate = self._gates.get(operation_id)
            worker = self._workers.get(operation_id)
        if gate is not None:
            gate.set()
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=30)

    def _period_plan(self, workspace_id: str, text: str, period: str) -> dict | None:
        focus = self._focus(workspace_id)
        previous_id = focus.get("last_plan_id")
        if not previous_id:
            return None
        try:
            previous = self._load(workspace_id, previous_id)
        except AppError:
            return None
        steps = list((previous.get("plan") or {}).get("steps") or [])
        if previous.get("status") != "succeeded" or not steps:
            return None
        plan = copy.deepcopy(previous["plan"])
        plan["id"] = str(uuid.uuid4())
        plan["workspace_id"] = workspace_id
        plan["user_text"] = text
        plan["steps"] = copy.deepcopy(steps)
        plan["ambiguities"] = []
        plan["requires_confirmation"] = False
        plan["confirmation_reasons"] = []
        plan["source"] = "rules"
        plan["period"] = period
        validate_plan(plan)
        return plan

    def _ask_report(self, workspace_id: str, text: str) -> dict:
        plan = _blank_plan(workspace_id)
        plan["user_text"] = text
        ambiguity = {"code": "plan.ambiguous", "question": PLAN_NEED_REPORT, "choices": []}
        plan["ambiguities"] = [ambiguity]
        return self._save(workspace_id, self._waiting(workspace_id, plan, ambiguity))

    def _is_cancelled(self, workspace_id: str, operation_id: str) -> bool:
        try:
            return self._load(workspace_id, operation_id)["status"] == "cancelled"
        except AppError:
            return False

    def _touch(self, workspace_id: str, operation_id: str, current: int, label: str) -> None:
        try:
            record = self._load(workspace_id, operation_id)
        except AppError:
            return
        if record["status"] != "running":
            return
        record["progress_current"] = current
        record["progress_label"] = label
        self._save(workspace_id, record)

    def _find_running(self, workspace_id: str) -> dict | None:
        with self.database.transaction() as conn:
            row = conn.execute(
                """
                SELECT plan_json FROM operations
                WHERE workspace_id = ? AND status = 'running'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (workspace_id,),
            ).fetchone()
        if row is None or not row["plan_json"]:
            return None
        record = json.loads(row["plan_json"])
        worker = self._workers.get(record["id"])
        if worker is not None and worker.is_alive():
            return record
        record["status"] = "failed"
        record["progress_label"] = "انجام نشد"
        record["summary"] = None
        record["outputs"] = []
        record["error"] = {"code": "internal", "message": "عملیات ناتمام ماند."}
        record["finished_at"] = _now()
        self._save(workspace_id, record)
        return None

    def _load_or_base(self, workspace_id: str, operation_id: str, plan: dict) -> dict:
        try:
            return self._load(workspace_id, operation_id)
        except AppError:
            return self._base(workspace_id, operation_id, plan)

    def _existing_files(self, workspace_id: str, file_ids: list[str] | None) -> list[str]:
        chosen = []
        for file_id in file_ids or []:
            if file_id not in chosen:
                self.files.get_file(workspace_id, file_id)
                chosen.append(file_id)
        return chosen

    def _focus(self, workspace_id: str) -> dict:
        with self.database.transaction() as conn:
            row = conn.execute(
                "SELECT focus_json FROM conversation_focus WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()
        if row is None:
            return dict(_EMPTY_FOCUS)
        return json.loads(row["focus_json"])

    def _save_focus(self, workspace_id: str, focus: dict) -> None:
        with self.database.transaction() as conn:
            conn.execute(
                """
                INSERT INTO conversation_focus (workspace_id, focus_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(workspace_id) DO UPDATE SET focus_json = excluded.focus_json, updated_at = excluded.updated_at
                """,
                (workspace_id, json.dumps(focus, ensure_ascii=False), _now()),
            )

    def _load(self, workspace_id: str, operation_id: str) -> dict:
        with self.database.transaction() as conn:
            row = conn.execute(
                "SELECT plan_json FROM operations WHERE id = ? AND workspace_id = ?",
                (operation_id, workspace_id),
            ).fetchone()
        if row is None or not row["plan_json"]:
            raise AppError("route.not_found", OPERATION_NOT_FOUND, 404)
        return json.loads(row["plan_json"])

    def _save(self, workspace_id: str, record: dict) -> dict:
        payload = json.dumps(record, ensure_ascii=False)
        error = record.get("error") or {}
        blocked = False
        with self.database.transaction() as conn:
            existing = conn.execute("SELECT id FROM operations WHERE id = ?", (record["id"],)).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO operations (
                        id, workspace_id, status, plan_json, summary, created_at, finished_at,
                        error_code, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["id"],
                        workspace_id,
                        record["status"],
                        payload,
                        record.get("summary"),
                        record["created_at"],
                        record["finished_at"],
                        error.get("code"),
                        error.get("message"),
                    ),
                )
            else:
                guard = "" if record["status"] == "cancelled" else " AND status != 'cancelled'"
                cursor = conn.execute(
                    f"""
                    UPDATE operations
                    SET status = ?, plan_json = ?, summary = ?, finished_at = ?, error_code = ?, error_message = ?
                    WHERE id = ? AND workspace_id = ?{guard}
                    """,
                    (
                        record["status"],
                        payload,
                        record.get("summary"),
                        record["finished_at"],
                        error.get("code"),
                        error.get("message"),
                        record["id"],
                        workspace_id,
                    ),
                )
                if cursor.rowcount == 0:
                    current = conn.execute(
                        "SELECT status FROM operations WHERE id = ? AND workspace_id = ?",
                        (record["id"], workspace_id),
                    ).fetchone()
                    if current is not None and current["status"] == "cancelled" and record["status"] != "cancelled":
                        blocked = True
        if blocked:
            return _public(self._load(workspace_id, record["id"]))
        return _public(record)

    def _base(self, workspace_id: str, operation_id: str, plan: dict) -> dict:
        created = _now()
        return {
            "id": operation_id,
            "status": "running",
            "progress_current": 0,
            "progress_total": max(len(plan.get("steps") or []), 1),
            "progress_label": "در حال اجرا",
            "summary": None,
            "warnings": [],
            "error": None,
            "outputs": [],
            "plan": plan,
            "llm_status": llm_status(self.settings),
            "pending": None,
            "created_at": created,
            "finished_at": created,
        }

    def _failed(self, workspace_id: str, exc: AppError, operation_id: str | None = None, plan: dict | None = None) -> dict:
        record = self._base(workspace_id, operation_id or str(uuid.uuid4()), plan or _blank_plan(workspace_id))
        record["status"] = "failed"
        record["progress_label"] = "انجام نشد"
        record["summary"] = None
        record["error"] = {"code": exc.code, "message": exc.message}
        return record

    def _waiting(self, workspace_id: str, plan: dict, ambiguity: dict, operation_id: str | None = None, pending: dict | None = None) -> dict:
        record = self._base(workspace_id, operation_id or plan["id"], plan)
        record["status"] = "waiting_confirmation"
        record["progress_current"] = 0
        record["progress_label"] = "منتظر پاسخ"
        record["summary"] = ambiguity["question"]
        record["pending"] = pending
        return record


def _public(record: dict) -> dict:
    body = dict(record)
    body.pop("pending", None)
    body.pop("created_at", None)
    return body


def _input_files(plan: dict, steps: list[dict]) -> list[str]:
    found = []
    for step in steps:
        params = step.get("params") or {}
        for key in ("file_id", "left_file_id", "right_file_id"):
            value = params.get(key)
            if value and value not in found:
                found.append(value)
    return found or list(plan.get("steps") and [])


def _blank_plan(workspace_id: str) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "workspace_id": workspace_id,
        "user_text": "",
        "goal": "",
        "steps": [],
        "ambiguities": [],
        "requires_confirmation": False,
        "confirmation_reasons": [],
        "risks": [],
        "source": "rules",
    }


def _check_names(names: list[str]) -> None:
    if len(names) > 8 or any(len(name) > 200 or not name.strip() for name in names):
        raise AppError("request.invalid", REQUEST_INVALID, 400)


def _workspace_lock(workspace_id: str) -> threading.Lock:
    with _GUARD:
        lock = _LOCKS.get(workspace_id)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[workspace_id] = lock
        return lock


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
