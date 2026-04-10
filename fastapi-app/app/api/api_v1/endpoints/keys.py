from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_secret, encrypt_secret, mask_key
from app.crud import llm_key as llm_key_crud
from app.db.session import get_db
from app.deps import get_current_user
from app.models.llm_credential import LLMCredential
from app.models.user import User
from app.schemas import LLMKeyCreate, LLMKeyOut

router = APIRouter(tags=["keys"])


def _key_out(row: LLMCredential) -> LLMKeyOut:
    try:
        hint = mask_key(decrypt_secret(row.secret_enc))
    except Exception:
        hint = "***"
    return LLMKeyOut(
        id=row.id,
        provider=row.provider,
        label=row.label,
        masked_hint=hint,
        created_at=row.created_at,
    )


@router.get("/me/keys", response_model=list[LLMKeyOut])
def list_keys(
    user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> list[LLMKeyOut]:
    rows = llm_key_crud.list_for_user(db, user.id)
    return [_key_out(r) for r in rows]


@router.post("/me/keys", response_model=LLMKeyOut)
def add_key(
    body: LLMKeyCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> LLMKeyOut:
    try:
        blob = encrypt_secret(body.api_key)
    except RuntimeError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    row = llm_key_crud.create(
        db,
        user_id=user.id,
        provider=body.provider,
        label=body.label,
        secret_enc=blob,
    )
    return _key_out(row)


@router.delete("/me/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_key(
    key_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> None:
    row = llm_key_crud.get_owned(db, key_id, user.id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Key not found")
    llm_key_crud.delete(db, row)
