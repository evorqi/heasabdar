from __future__ import annotations

import secrets

from fastapi import Request

from hesabdar.errors import AppError
from hesabdar.messages import FORBIDDEN


def authorize(request: Request) -> None:
    expected = request.app.state.ctx.settings.access_token
    if not expected:
        return
    header = request.headers.get("authorization", "")
    prefix = "Bearer "
    provided = header[len(prefix) :] if header.startswith(prefix) else ""
    if not provided or not _matches(provided, expected):
        raise AppError("workspace.forbidden", FORBIDDEN, 403)


def _matches(provided: str, expected: str) -> bool:
    try:
        return secrets.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))
    except Exception:
        return False
