from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.crud import job as job_crud
from app.db.session import get_db
from app.deps import get_current_user
from app.models.job import Job
from app.models.user import User
from app.schemas import JobOut, RenderJsonBody, RenderOptions
from app.services import rate_limit
from app.services.paths import job_dir as job_dir_fn
from app.services.pipeline_runner import (
    PipelineInputError,
    PipelinePlanError,
    ensure_pdf_exists,
    ensure_pptx_exists,
    run_pipeline_locked,
)
from app.services.runtime_merge import build_runtime_config
from app.core.config import get_settings

router = APIRouter(prefix="/jobs", tags=["jobs"])
logger = logging.getLogger("pdf_pipeline.api")

_MAX_TEXT_CHARS = 2_000_000  # ~2 MB of plain text


def _check_rate_limit(user_id: str) -> None:
    s = get_settings()
    allowed, retry_after = rate_limit.check(
        key=f"job:{user_id}",
        limit=s.job_rate_limit,
        window_secs=60,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Try again in {retry_after}s.",
            headers={"Retry-After": str(retry_after)},
        )


def _check_upload_size(content: bytes) -> None:
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File exceeds {get_settings().max_upload_mb} MB limit.",
        )


def _execute_job(
    *,
    db: Session,
    user: User,
    job: Job,
    input_path: Path,
    stem: str,
    options: RenderOptions | None,
    html_only: bool,
) -> tuple[Path, Path]:
    work_dir = job_dir_fn(user.id, job.id)
    work_dir.mkdir(parents=True, exist_ok=True)
    output_format = (options.output_format if options else None) or "pdf"
    out_ext = ".pptx" if output_format == "pptx" else ".pdf"
    out_file = work_dir / f"{stem}{out_ext}"
    runtime = build_runtime_config(db, user, options)
    run_pipeline_locked(
        str(input_path), str(out_file),
        runtime_overrides=runtime, html_only=html_only,
        output_format=output_format,
    )
    final_html = work_dir / f"{stem}.html"
    if not html_only:
        if output_format == "pptx":
            ensure_pptx_exists(final_html, out_file)
        else:
            ensure_pdf_exists(final_html, out_file)
    return work_dir, out_file


@router.post("/render-json")
def render_json(
    body: RenderJsonBody,
    user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    _check_rate_limit(user.id)

    if body.text is not None and len(body.text) > _MAX_TEXT_CHARS:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Text exceeds {_MAX_TEXT_CHARS // 1_000_000} MB limit.",
        )

    job = job_crud.create_running(
        db,
        user_id=user.id,
        input_filename="body.json" if body.structured is not None else "body.txt",
    )

    work_dir = job_dir_fn(user.id, job.id)
    work_dir.mkdir(parents=True, exist_ok=True)
    stem = f"report_{job.id[:8]}"

    if body.text is not None:
        raw = body.text
        suffix = ".txt"
    else:
        raw = json.dumps(body.structured, ensure_ascii=False, indent=2)
        suffix = ".json"

    in_path = work_dir / f"input{suffix}"
    in_path.write_text(raw, encoding="utf-8", errors="replace")

    opts = RenderOptions.model_validate(body.model_dump(exclude={"text", "structured"}))
    html_only = body.html_only
    output_format = opts.output_format or "pdf"

    try:
        wd, out_file = _execute_job(
            db=db,
            user=user,
            job=job,
            input_path=in_path,
            stem=stem,
            options=opts,
            html_only=html_only,
        )
        job.status = "done"
        job.work_dir = str(wd)
        job.output_pdf_path = str(out_file) if out_file.exists() else None
        job.result_json = {"stem": stem, "html_only": html_only, "output_format": output_format}
        job.completed_at = datetime.utcnow()
        job_crud.save(db, job)
    except (PipelineInputError, PipelinePlanError, RuntimeError, ValueError) as e:
        logger.exception("Job %s failed", job.id)
        job.status = "failed"
        job.error_message = str(e)[:8000]
        job.completed_at = datetime.utcnow()
        job_crud.save(db, job)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        logger.exception("Job %s failed (unexpected)", job.id)
        job.status = "failed"
        job.error_message = str(e)[:8000]
        job.completed_at = datetime.utcnow()
        job_crud.save(db, job)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Pipeline failed") from e

    if html_only:
        html_file = wd / f"{stem}.html"
        if not html_file.exists():
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "HTML output missing")
        return FileResponse(html_file, media_type="text/html", filename=f"{stem}.html")

    if not out_file.exists():
        if output_format == "pptx":
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "PPTX was not produced (install Playwright + python-pptx).",
            )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "PDF was not produced (install Playwright + chromium or pdfkit). HTML is in job folder.",
        )

    if output_format == "pptx":
        return FileResponse(
            out_file,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            filename=f"{stem}.pptx",
        )
    return FileResponse(out_file, media_type="application/pdf", filename=f"{stem}.pdf")


@router.post("/render-file")
async def render_file(
    user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
    file: UploadFile | None = File(None),
    text: str | None = Form(None),
    options: str | None = Form(None),
):
    _check_rate_limit(user.id)

    if (file is None or not file.filename) and (text is None or not str(text).strip()):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Provide either `file` or non-empty `text`",
        )
    if file is not None and file.filename and text is not None and str(text).strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Provide only one of `file` or `text`",
        )

    opts: RenderOptions | None = None
    if options:
        try:
            opts = RenderOptions.model_validate_json(options)
        except ValidationError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e

    html_only = opts.html_only if opts else False
    output_format = (opts.output_format if opts else None) or "pdf"

    job = job_crud.create_running(
        db,
        user_id=user.id,
        input_filename=file.filename if file and file.filename else "form_text.txt",
    )

    work_dir = job_dir_fn(user.id, job.id)
    work_dir.mkdir(parents=True, exist_ok=True)
    stem = f"report_{job.id[:8]}"

    try:
        if file is not None and file.filename:
            suffix = Path(file.filename).suffix.lower() or ".txt"
            if suffix not in {".pdf", ".csv", ".txt", ".json", ".md"}:
                suffix = ".txt"
            in_path = work_dir / f"input{suffix}"
            content = await file.read()
            _check_upload_size(content)
            if suffix == ".pdf":
                in_path.write_bytes(content)
            else:
                in_path.write_text(content.decode("utf-8", errors="replace"), encoding="utf-8")
        else:
            raw_text = str(text)
            if len(raw_text) > _MAX_TEXT_CHARS:
                raise HTTPException(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    f"Text exceeds {_MAX_TEXT_CHARS // 1_000_000} MB limit.",
                )
            in_path = work_dir / "input.txt"
            in_path.write_text(raw_text, encoding="utf-8", errors="replace")

        wd, out_file = _execute_job(
            db=db,
            user=user,
            job=job,
            input_path=in_path,
            stem=stem,
            options=opts,
            html_only=html_only,
        )
        job.status = "done"
        job.work_dir = str(wd)
        job.output_pdf_path = str(out_file) if out_file.exists() else None
        job.result_json = {"stem": stem, "html_only": html_only, "output_format": output_format}
        job.completed_at = datetime.utcnow()
        job_crud.save(db, job)
    except HTTPException:
        raise
    except (PipelineInputError, PipelinePlanError, RuntimeError, ValueError) as e:
        logger.exception("Job %s failed", job.id)
        job.status = "failed"
        job.error_message = str(e)[:8000]
        job.completed_at = datetime.utcnow()
        job_crud.save(db, job)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        logger.exception("Job %s failed (unexpected)", job.id)
        job.status = "failed"
        job.error_message = str(e)[:8000]
        job.completed_at = datetime.utcnow()
        job_crud.save(db, job)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Pipeline failed") from e

    if html_only:
        html_file = wd / f"{stem}.html"
        if not html_file.exists():
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "HTML output missing")
        return FileResponse(html_file, media_type="text/html", filename=f"{stem}.html")

    if not out_file.exists():
        if output_format == "pptx":
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "PPTX was not produced (install Playwright + python-pptx).",
            )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "PDF was not produced (install Playwright + chromium or pdfkit).",
        )

    if output_format == "pptx":
        return FileResponse(
            out_file,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            filename=f"{stem}.pptx",
        )
    return FileResponse(out_file, media_type="application/pdf", filename=f"{stem}.pdf")


@router.get("", response_model=list[JobOut])
def list_jobs(
    user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
    limit: int = 50,
) -> list[Job]:
    lim = max(1, min(limit, 200))
    return job_crud.list_for_user(db, user.id, lim)


@router.get("/{job_id}", response_model=JobOut)
def get_job(
    job_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> Job:
    job = job_crud.get_owned(db, job_id, user.id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return job


@router.get("/{job_id}/stream")
async def stream_job_status(
    job_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Server-Sent Events stream for job progress. Closes when job reaches done/failed."""
    job = job_crud.get_owned(db, job_id, user.id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")

    async def _event_gen():
        for _ in range(300):  # max ~10 minutes at 2s intervals
            db.expire_all()
            current = job_crud.get_owned(db, job_id, user.id)
            if current is None:
                payload = json.dumps({"status": "not_found"})
                yield f"data: {payload}\n\n"
                break

            payload = json.dumps({
                "status": current.status,
                "error": current.error_message,
                "completed_at": current.completed_at.isoformat() if current.completed_at else None,
            })
            yield f"data: {payload}\n\n"

            if current.status in ("done", "failed"):
                break
            await asyncio.sleep(2)

    return StreamingResponse(_event_gen(), media_type="text/event-stream")


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(
    job_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> None:
    job = job_crud.get_owned(db, job_id, user.id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    if job.status == "running":
        raise HTTPException(status.HTTP_409_CONFLICT, "Cannot delete a running job")
    job_crud.delete_job(db, job)


@router.get("/{job_id}/download")
def download_job_pdf(
    job_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    job = job_crud.get_owned(db, job_id, user.id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    if job.status != "done":
        return JSONResponse({"status": job.status, "error": job.error_message}, status_code=400)
    result = job.result_json or {}
    html_only = bool(result.get("html_only"))
    output_format = result.get("output_format", "pdf")
    stem = result.get("stem") or f"report_{job.id[:8]}"
    wd = Path(job.work_dir or job_dir_fn(user.id, job.id))

    if html_only:
        hf = wd / f"{stem}.html"
        if not hf.exists():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "HTML not found on disk")
        return FileResponse(hf, media_type="text/html", filename=f"{stem}.html")

    out_ext = ".pptx" if output_format == "pptx" else ".pdf"
    pp = Path(job.output_pdf_path) if job.output_pdf_path else wd / f"{stem}{out_ext}"
    if not pp.exists():
        hf = wd / f"{stem}.html"
        if hf.exists():
            if output_format == "pptx":
                if ensure_pptx_exists(hf, pp):
                    job.output_pdf_path = str(pp)
                    job_crud.save(db, job)
            else:
                if ensure_pdf_exists(hf, pp):
                    job.output_pdf_path = str(pp)
                    job_crud.save(db, job)

    if not pp.exists():
        label = "PPTX" if output_format == "pptx" else "PDF"
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label} not available")

    if output_format == "pptx":
        return FileResponse(
            pp,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            filename=pp.name,
        )
    return FileResponse(pp, media_type="application/pdf", filename=pp.name)
