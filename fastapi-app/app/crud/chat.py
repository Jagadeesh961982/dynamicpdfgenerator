from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.chat import ChatMessage, ChatThread


def create_thread(db: Session, *, user_id: str, title: str) -> ChatThread:
    t = ChatThread(id=str(uuid.uuid4()), user_id=user_id, title=title)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def list_threads(db: Session, user_id: str) -> list[ChatThread]:
    return (
        db.query(ChatThread)
        .filter(ChatThread.user_id == user_id)
        .order_by(ChatThread.created_at.desc())
        .all()
    )


def get_thread_owned(db: Session, thread_id: str, user_id: str) -> ChatThread | None:
    return (
        db.query(ChatThread)
        .filter(ChatThread.id == thread_id, ChatThread.user_id == user_id)
        .one_or_none()
    )


def add_message(db: Session, *, thread_id: str, role: str, content: str) -> ChatMessage:
    msg = ChatMessage(id=str(uuid.uuid4()), thread_id=thread_id, role=role, content=content)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def delete_thread(db: Session, thread: ChatThread) -> None:
    db.delete(thread)
    db.commit()
