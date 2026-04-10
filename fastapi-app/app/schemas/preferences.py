from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.render import AgentModels, Provider

# Re-export for convenience
__all__ = ["PreferencesBody", "PreferencesOut", "AgentModels", "Provider"]


class PreferencesBody(BaseModel):
    """Stored defaults merged into each render job."""

    provider: Provider | None = None
    models: AgentModels | None = None
    model_all: str | None = Field(
        None,
        description="If set, applies this model to all agents (overrides per-agent when applied)",
    )
    visual_style: Literal["notebooklm", "modern", "dark", "auto"] | None = None
    max_iterations: int | None = Field(None, ge=1, le=20)
    pass_threshold: float | None = Field(None, ge=0, le=10)
    max_data_chars: int | None = Field(None, ge=1000)


class PreferencesOut(BaseModel):
    settings: dict[str, Any]
