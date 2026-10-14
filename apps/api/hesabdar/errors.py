from __future__ import annotations


class AppError(Exception):
    """خطای قابل‌نمایش برای کاربر. جزئیات دیسک و محتوای سلول اینجا نیست."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int,
        detail: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail


class UnsafeBind(Exception):
    """شروع سرویس روی شبکه بدون توکن مجاز نیست."""
