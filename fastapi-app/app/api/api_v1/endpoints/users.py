from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.crud import preference as preference_crud
from app.db.session import get_db
from app.deps import get_current_user
from app.models.user import User
from app.schemas import PreferencesBody, PreferencesOut, UserOut
from app.services.runtime_merge import upsert_preferences

router = APIRouter(tags=["users"])


@router.get("/me", response_model=UserOut)
def me(user: Annotated[User, Depends(get_current_user)]) -> User:
    return user


@router.get("/me/preferences", response_model=PreferencesOut)
def get_preferences(
    user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> PreferencesOut:
    row = preference_crud.get_for_user(db, user.id)
    return PreferencesOut(settings=dict(row.settings_json or {}) if row else {})


@router.put("/me/preferences", response_model=PreferencesOut)
def put_preferences(
    body: PreferencesBody,
    user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> PreferencesOut:
    settings = upsert_preferences(db, user.id, body)
    return PreferencesOut(settings=settings)
