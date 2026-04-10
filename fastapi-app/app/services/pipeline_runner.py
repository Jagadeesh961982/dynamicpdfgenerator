from __future__ import annotations

import logging
import threading
import uuid
from pathlib import Path

from orchestrator import (
    PipelineInputError,
    PipelinePlanError,
    export_pdf,
    load,
    run as pipeline_run,
)

from app.services.config_runtime import apply_runtime_config, restore_config, snapshot_config

logger = logging.getLogger(__name__)

_run_lock = threading.Lock()


def write_temp_input(parent: Path, content: str, suffix: str) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    p = parent / f"input_{uuid.uuid4().hex}{suffix}"
    p.write_text(content, encoding="utf-8", errors="replace")
    return p


def run_pipeline_locked(
    input_path: str,
    output_pdf_path: str,
    *,
    runtime_overrides: dict | None,
    html_only: bool = False,
) -> None:
    """Run the pipeline with exclusive lock (global `config` is mutated)."""
    with _run_lock:
        snap = snapshot_config()
        try:
            if runtime_overrides:
                apply_runtime_config(runtime_overrides)
            pipeline_run(input_path, output_pdf_path, html_only=html_only)
        finally:
            restore_config(snap)


def run_pipeline_from_text(
    raw_text: str,
    work_dir: Path,
    *,
    runtime_overrides: dict | None,
    input_suffix: str = ".txt",
    stem: str | None = None,
    html_only: bool = False,
) -> tuple[Path, Path]:
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    stem = stem or f"job_{uuid.uuid4().hex[:12]}"
    in_path = write_temp_input(work_dir, raw_text, input_suffix)
    out_pdf = work_dir / f"{stem}.pdf"
    run_pipeline_locked(str(in_path), str(out_pdf), runtime_overrides=runtime_overrides, html_only=html_only)
    return work_dir, out_pdf


def ensure_pdf_exists(html_path: Path, pdf_path: Path) -> bool:
    if pdf_path.exists():
        return True
    hp = html_path
    if hp.exists():
        return export_pdf(str(hp), str(pdf_path))
    return False


__all__ = [
    "PipelineInputError",
    "PipelinePlanError",
    "load",
    "run_pipeline_locked",
    "run_pipeline_from_text",
    "ensure_pdf_exists",
    "write_temp_input",
]
