from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings


def storage_base() -> Path:
    return get_settings().storage_root_resolved()


def job_dir(user_id: str, job_id: str) -> Path:
    return storage_base() / user_id / job_id
