from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.job import Job


def create_running(
    db: Session,
    *,
    user_id: str,
    input_filename: str | None,
) -> Job:
    job = Job(
        id=str(uuid.uuid4()),
        user_id=user_id,
        status="running",
        input_filename=input_filename,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def get_owned(db: Session, job_id: str, user_id: str) -> Job | None:
    return db.query(Job).filter(Job.id == job_id, Job.user_id == user_id).one_or_none()


def list_for_user(db: Session, user_id: str, limit: int) -> list[Job]:
    return (
        db.query(Job)
        .filter(Job.user_id == user_id)
        .order_by(Job.created_at.desc())
        .limit(limit)
        .all()
    )


def save(db: Session, job: Job) -> None:
    db.commit()
    db.refresh(job)


def delete_job(db: Session, job: Job) -> None:
    db.delete(job)
    db.commit()
