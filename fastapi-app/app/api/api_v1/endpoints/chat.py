from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.crud import chat as chat_crud
from app.db.session import get_db
from app.deps import get_current_user
from app.models.chat import ChatMessage, ChatThread
from app.models.user import User
from app.schemas import ChatMessageCreate, ChatMessageOut, ChatThreadCreate, ChatThreadOut

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/threads", response_model=ChatThreadOut)
def create_thread(
    body: ChatThreadCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> ChatThread:
    return chat_crud.create_thread(db, user_id=user.id, title=body.title)


@router.get("/threads", response_model=list[ChatThreadOut])
def list_threads(
    user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> list[ChatThread]:
    return chat_crud.list_threads(db, user.id)


@router.get("/threads/{thread_id}/messages", response_model=list[ChatMessageOut])
def list_messages(
    thread_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> list[ChatMessage]:
    th = chat_crud.get_thread_owned(db, thread_id, user.id)
    if th is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found")
    return sorted(th.messages, key=lambda m: m.created_at)


@router.post("/threads/{thread_id}/messages", response_model=ChatMessageOut)
def add_message(
    thread_id: str,
    body: ChatMessageCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> ChatMessage:
    if chat_crud.get_thread_owned(db, thread_id, user.id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found")
    return chat_crud.add_message(db, thread_id=thread_id, role=body.role, content=body.content)
