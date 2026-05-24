from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.user import User
from app.schemas.user import UserCreate


def get_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email.lower()).one_or_none()


def create_user(db: Session, body: UserCreate, hashed_password: str) -> User:
    import uuid

    user = User(
        id=str(uuid.uuid4()),
        email=body.email.lower(),
        hashed_password=hashed_password,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
