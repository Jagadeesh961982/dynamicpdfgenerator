from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.crud import job as job_crud
from app.db.session import get_db
from app.deps import get_current_user
from app.models.job import Job
from app.models.user import User
from app.schemas import JobOut, RenderJsonBody, RenderOptions
from app.services.paths import job_dir as job_dir_fn
from app.services.pipeline_runner import (
    PipelineInputError,
    PipelinePlanError,
    ensure_pdf_exists,
    run_pipeline_locked,
)
from app.services.runtime_merge import build_runtime_config

router = APIRouter(prefix="/jobs", tags=["jobs"])
logger = logging.getLogger("pdf_pipeline.api")


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
    out_pdf = work_dir / f"{stem}.pdf"
    runtime = build_runtime_config(db, user, options)
    run_pipeline_locked(str(input_path), str(out_pdf), runtime_overrides=runtime, html_only=html_only)
    final_html = work_dir / f"{stem}.html"
    if not html_only:
        ensure_pdf_exists(final_html, out_pdf)
    return work_dir, out_pdf


@router.post("/render-json")
def render_json(
    body: RenderJsonBody,
    user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
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
    pdf_path = work_dir / f"{stem}.pdf"

    try:
        wd, pdf_path = _execute_job(
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
        job.output_pdf_path = str(pdf_path) if pdf_path.exists() else None
        job.result_json = {"stem": stem, "html_only": html_only}
        job.completed_at = datetime.utcnow()
        job_crud.save(db, job)
    except (PipelineInputError, PipelinePlanError, RuntimeError, ValueError) as e:
        logger.exception("Job failed")
        job.status = "failed"
        job.error_message = str(e)[:8000]
        job.completed_at = datetime.utcnow()
        job_crud.save(db, job)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        logger.exception("Job failed")
        job.status = "failed"
        job.error_message = str(e)[:8000]
        job.completed_at = datetime.utcnow()
        job_crud.save(db, job)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Pipeline failed") from e

    if html_only:
        html_file = work_dir / f"{stem}.html"
        if not html_file.exists():
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "HTML output missing")
        return FileResponse(html_file, media_type="text/html", filename=f"{stem}.html")

    if not pdf_path.exists():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "PDF was not produced (install Playwright + chromium or pdfkit). HTML is in job folder.",
        )
    return FileResponse(pdf_path, media_type="application/pdf", filename=f"{stem}.pdf")


@router.post("/render-file")
async def render_file(
    user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
    file: UploadFile | None = File(None),
    text: str | None = Form(None),
    options: str | None = Form(None),
):
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

    job = job_crud.create_running(
        db,
        user_id=user.id,
        input_filename=file.filename if file and file.filename else "form_text.txt",
    )

    work_dir = job_dir_fn(user.id, job.id)
    work_dir.mkdir(parents=True, exist_ok=True)
    stem = f"report_{job.id[:8]}"
    pdf_path = work_dir / f"{stem}.pdf"

    try:
        if file is not None and file.filename:
            suffix = Path(file.filename).suffix.lower() or ".txt"
            if suffix not in {".pdf", ".csv", ".txt", ".json", ".md"}:
                suffix = ".txt"
            in_path = work_dir / f"input{suffix}"
            content = await file.read()
            if suffix == ".pdf":
                in_path.write_bytes(content)
            else:
                in_path.write_text(content.decode("utf-8", errors="replace"), encoding="utf-8")
        else:
            in_path = work_dir / "input.txt"
            in_path.write_text(str(text), encoding="utf-8", errors="replace")

        wd, pdf_path = _execute_job(
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
        job.output_pdf_path = str(pdf_path) if pdf_path.exists() else None
        job.result_json = {"stem": stem, "html_only": html_only}
        job.completed_at = datetime.utcnow()
        job_crud.save(db, job)
    except (PipelineInputError, PipelinePlanError, RuntimeError, ValueError) as e:
        logger.exception("Job failed")
        job.status = "failed"
        job.error_message = str(e)[:8000]
        job.completed_at = datetime.utcnow()
        job_crud.save(db, job)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        logger.exception("Job failed")
        job.status = "failed"
        job.error_message = str(e)[:8000]
        job.completed_at = datetime.utcnow()
        job_crud.save(db, job)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Pipeline failed") from e

    if html_only:
        html_file = work_dir / f"{stem}.html"
        if not html_file.exists():
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "HTML output missing")
        return FileResponse(html_file, media_type="text/html", filename=f"{stem}.html")

    if not pdf_path.exists():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "PDF was not produced (install Playwright + chromium or pdfkit).",
        )
    return FileResponse(pdf_path, media_type="application/pdf", filename=f"{stem}.pdf")


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
    html_only = bool(job.result_json and job.result_json.get("html_only"))
    stem = (job.result_json or {}).get("stem") or f"report_{job.id[:8]}"
    wd = Path(job.work_dir or job_dir_fn(user.id, job.id))
    if html_only:
        hf = wd / f"{stem}.html"
        if not hf.exists():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "HTML not found on disk")
        return FileResponse(hf, media_type="text/html", filename=f"{stem}.html")
    pp = Path(job.output_pdf_path) if job.output_pdf_path else wd / f"{stem}.pdf"
    if not pp.exists():
        hf = wd / f"{stem}.html"
        if hf.exists() and ensure_pdf_exists(hf, pp):
            job.output_pdf_path = str(pp)
            job_crud.save(db, job)
    if not pp.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "PDF not available")
    return FileResponse(pp, media_type="application/pdf", filename=pp.name)
