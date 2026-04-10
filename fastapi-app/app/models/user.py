from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    preferences: Mapped[UserPreference | None] = relationship(
        "UserPreference",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    llm_keys: Mapped[list[LLMCredential]] = relationship(
        "LLMCredential",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    jobs: Mapped[list[Job]] = relationship(
        "Job",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    chat_threads: Mapped[list[ChatThread]] = relationship(
        "ChatThread",
        back_populates="user",
        cascade="all, delete-orphan",
    )
