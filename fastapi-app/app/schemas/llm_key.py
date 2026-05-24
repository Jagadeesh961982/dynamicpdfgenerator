from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.render import Provider


class LLMKeyCreate(BaseModel):
    provider: Provider
    api_key: str = Field(min_length=1, max_length=4096)
    label: str = Field(default="default", max_length=128)


class LLMKeyOut(BaseModel):
    id: str
    provider: str
    label: str
    masked_hint: str
    created_at: datetime

    model_config = {"from_attributes": True}
