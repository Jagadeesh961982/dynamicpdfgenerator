from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ChatThreadCreate(BaseModel):
    title: str = Field(default="Chat", max_length=256)


class ChatThreadOut(BaseModel):
    id: str
    title: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatMessageCreate(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str = Field(min_length=1, max_length=200_000)


class ChatMessageOut(BaseModel):
    id: str
    thread_id: str
    role: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}
