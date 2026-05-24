from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.llm_credential import LLMCredential


def list_for_user(db: Session, user_id: str) -> list[LLMCredential]:
    return (
        db.query(LLMCredential)
        .filter(LLMCredential.user_id == user_id)
        .order_by(LLMCredential.created_at.desc())
        .all()
    )


def create(db: Session, *, user_id: str, provider: str, label: str, secret_enc: bytes) -> LLMCredential:
    row = LLMCredential(
        id=str(uuid.uuid4()),
        user_id=user_id,
        provider=provider,
        label=label,
        secret_enc=secret_enc,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_owned(db: Session, key_id: str, user_id: str) -> LLMCredential | None:
    return (
        db.query(LLMCredential)
        .filter(LLMCredential.id == key_id, LLMCredential.user_id == user_id)
        .one_or_none()
    )


def delete(db: Session, row: LLMCredential) -> None:
    db.delete(row)
    db.commit()
