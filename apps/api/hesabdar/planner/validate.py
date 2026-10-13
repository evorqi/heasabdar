from __future__ import annotations

from hesabdar.errors import AppError
from hesabdar.messages import PLAN_REJECTED
from hesabdar.planner.registry import TOOLS

_FORBIDDEN_KEYS = {"code", "script", "shell"}
_CODE = (
    "os.system",
    "subprocess",
    "__import__",
    "eval(",
    "exec(",
    "import ",
    "lambda ",
    "def ",
)


def validate_plan(plan: dict) -> None:
    steps = plan.get("steps")
    if not isinstance(steps, list):
        raise AppError("plan.unknown_tool", PLAN_REJECTED, 422)
    for step in steps:
        if not isinstance(step, dict):
            raise AppError("plan.unknown_tool", PLAN_REJECTED, 422)
        tool = step.get("tool")
        if tool not in TOOLS:
            raise AppError("plan.unknown_tool", PLAN_REJECTED, 422)
        params = step.get("params")
        if not isinstance(params, dict):
            raise AppError("plan.unknown_tool", PLAN_REJECTED, 422)
        for key, value in params.items():
            if key in _FORBIDDEN_KEYS or _bad_value(value):
                raise AppError("plan.unknown_tool", PLAN_REJECTED, 422)
        for bucket in ("reads", "writes"):
            values = step.get(bucket)
            if not isinstance(values, list) or any(_bad_value(item) for item in values):
                raise AppError("plan.unknown_tool", PLAN_REJECTED, 422)


def looks_like_code(text: str) -> bool:
    lowered = text.casefold()
    if any(token in lowered for token in _CODE):
        return True
    if ".." in text or text.strip().startswith("/") or "\\" in text:
        return True
    return " shell " in f" {lowered} " or lowered.strip() == "shell"


def _bad_value(value) -> bool:
    if not isinstance(value, str):
        return False
    if value.startswith("/") or value.startswith("\\") or ".." in value:
        return True
    lowered = value.casefold()
    return any(token in lowered for token in _CODE)
