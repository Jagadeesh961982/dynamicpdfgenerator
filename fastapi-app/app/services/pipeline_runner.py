from __future__ import annotations

import logging
import threading
import uuid
from pathlib import Path

from orchestrator import (
    PipelineInputError,
    PipelinePlanError,
    export_pdf,
    export_pptx,
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
    output_path: str,
    *,
    runtime_overrides: dict | None,
    html_only: bool = False,
    output_format: str = "pdf",
) -> None:
    """Run the pipeline with exclusive lock (global `config` is mutated)."""
    with _run_lock:
        snap = snapshot_config()
        try:
            if runtime_overrides:
                apply_runtime_config(runtime_overrides)
            pipeline_run(input_path, output_path, html_only=html_only, output_format=output_format)
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
    output_format: str = "pdf",
) -> tuple[Path, Path]:
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    stem = stem or f"job_{uuid.uuid4().hex[:12]}"
    in_path = write_temp_input(work_dir, raw_text, input_suffix)
    out_ext = ".pptx" if output_format == "pptx" else ".pdf"
    out_file = work_dir / f"{stem}{out_ext}"
    run_pipeline_locked(str(in_path), str(out_file), runtime_overrides=runtime_overrides, html_only=html_only, output_format=output_format)
    return work_dir, out_file


def ensure_pdf_exists(html_path: Path, pdf_path: Path) -> bool:
    if pdf_path.exists():
        return True
    if html_path.exists():
        return export_pdf(str(html_path), str(pdf_path))
    return False


def ensure_pptx_exists(html_path: Path, pptx_path: Path) -> bool:
    if pptx_path.exists():
        return True
    if html_path.exists():
        return export_pptx(str(html_path), str(pptx_path))
    return False


__all__ = [
    "PipelineInputError",
    "PipelinePlanError",
    "load",
    "run_pipeline_locked",
    "run_pipeline_from_text",
    "ensure_pdf_exists",
    "ensure_pptx_exists",
    "write_temp_input",
]
