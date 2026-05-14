"""Admin endpoints — usage stats and job cleanup.

These endpoints require a valid user account (same auth as regular users).
In production, add role-based access control before exposing to non-admins.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.crud import job as job_crud
from app.db.session import get_db
from app.deps import get_current_user
from app.models.job import Job
from app.models.user import User
from app.services.paths import job_dir as job_dir_fn

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats")
def stats(
    user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> dict:
    """Return aggregate usage statistics for the current user."""
    jobs: list[Job] = job_crud.list_for_user(db, user.id, limit=1000)
    total = len(jobs)
    done = sum(1 for j in jobs if j.status == "done")
    failed = sum(1 for j in jobs if j.status == "failed")
    running = sum(1 for j in jobs if j.status == "running")
    return {
        "total_jobs": total,
        "done": done,
        "failed": failed,
        "running": running,
        "member_since": user.created_at.isoformat(),
    }


@router.delete("/jobs/cleanup")
def cleanup_old_jobs(
    user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
    older_than_days: int = Query(default=30, ge=1, le=365),
    delete_files: bool = Query(default=False),
) -> dict:
    """Delete completed/failed jobs older than N days.

    Set delete_files=true to also remove job artifacts from disk.
    Returns count of deleted records.
    """
    cutoff = datetime.utcnow() - timedelta(days=older_than_days)
    jobs: list[Job] = (
        db.query(Job)
        .filter(
            Job.user_id == user.id,
            Job.status.in_(("done", "failed")),
            Job.completed_at < cutoff,
        )
        .all()
    )

    deleted_files = 0
    for job in jobs:
        if delete_files and job.work_dir:
            wd = Path(job.work_dir)
            if wd.exists() and wd.is_dir():
                shutil.rmtree(wd, ignore_errors=True)
                deleted_files += 1
        db.delete(job)

    db.commit()
    return {
        "deleted_jobs": len(jobs),
        "deleted_file_dirs": deleted_files,
        "cutoff": cutoff.isoformat(),
    }
