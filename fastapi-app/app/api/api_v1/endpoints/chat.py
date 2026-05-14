from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.crud import chat as chat_crud
from app.db.session import get_db
from app.deps import get_current_user
from app.models.chat import ChatMessage, ChatThread
from app.models.user import User
from app.schemas import (
    ChatMessageCreate,
    ChatMessageOut,
    ChatRequest,
    ChatThreadCreate,
    ChatThreadOut,
)
from app.services.runtime_merge import build_runtime_config
from app.services.config_runtime import apply_runtime_config, restore_config, snapshot_config

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger("pdf_pipeline.api")

_SYSTEM_PROMPT = (
    "You are a helpful AI assistant embedded in a PDF report generation tool. "
    "You help users understand their data, brainstorm report topics, and answer "
    "questions about their generated reports. Be concise and informative."
)


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


@router.delete("/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_thread(
    thread_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> None:
    th = chat_crud.get_thread_owned(db, thread_id, user.id)
    if th is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found")
    chat_crud.delete_thread(db, th)


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


@router.post("/threads/{thread_id}/chat", response_model=ChatMessageOut)
def chat(
    thread_id: str,
    body: ChatRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> ChatMessage:
    """Send a user message and receive an AI response. Stores both in thread history."""
    th = chat_crud.get_thread_owned(db, thread_id, user.id)
    if th is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found")

    # Build conversation history as OpenAI-style messages
    history = sorted(th.messages, key=lambda m: m.created_at)
    messages: list[dict] = [
        {"role": "system", "content": body.system_prompt or _SYSTEM_PROMPT}
    ]
    messages.extend({"role": m.role, "content": m.content} for m in history)
    messages.append({"role": "user", "content": body.message})

    # Store the user message first (before LLM call, so it's persisted even on error)
    chat_crud.add_message(db, thread_id=thread_id, role="user", content=body.message)

    # Apply user's LLM credentials/provider preferences for this call
    snap = snapshot_config()
    try:
        runtime = build_runtime_config(db, user, job_options=None)
        if runtime:
            apply_runtime_config(runtime)

        from utils.llm import call_messages
        response_text = call_messages(messages, max_tokens=2000)
    except RuntimeError as e:
        logger.warning("Chat LLM call failed for user %s: %s", user.id[:8], e)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"LLM unavailable: {e}",
        ) from e
    except Exception as e:
        logger.exception("Unexpected error in chat for user %s", user.id[:8])
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Chat error") from e
    finally:
        restore_config(snap)

    return chat_crud.add_message(db, thread_id=thread_id, role="assistant", content=response_text)
