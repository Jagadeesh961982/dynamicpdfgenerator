from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.preference import UserPreference
from app.schemas.preferences import PreferencesBody


def get_for_user(db: Session, user_id: str) -> UserPreference | None:
    return db.query(UserPreference).filter(UserPreference.user_id == user_id).one_or_none()


def upsert_merge(db: Session, user_id: str, body: PreferencesBody) -> dict:
    row = get_for_user(db, user_id)
    data = body.model_dump(exclude_none=True)
    if row is None:
        row = UserPreference(user_id=user_id, settings_json=data)
        db.add(row)
    else:
        base = dict(row.settings_json or {})
        base.update(data)
        row.settings_json = base
    db.commit()
    db.refresh(row)
    return row.settings_json or {}
