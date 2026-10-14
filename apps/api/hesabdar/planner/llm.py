from __future__ import annotations

from hesabdar.config import Settings
from hesabdar.messages import LLM_UNCONFIGURED


def llm_status(settings: Settings) -> str:
    if settings.llm_base_url and settings.llm_api_key and settings.llm_model:
        return "پیکربندی شده"
    return LLM_UNCONFIGURED
