from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

Provider = Literal["openrouter", "gemini", "nvidia"]


class AgentModels(BaseModel):
    analyzer: str | None = None
    planner: str | None = None
    designer: str | None = None
    assembler: str | None = None
    critic: str | None = None


class RenderOptions(BaseModel):
    """Per-job overrides (optional)."""

    provider: Provider | None = None
    models: AgentModels | None = None
    model_all: str | None = None
    visual_style: Literal["notebooklm", "modern", "dark", "auto"] | None = None
    max_iterations: int | None = Field(None, ge=1, le=20)
    pass_threshold: float | None = Field(None, ge=0, le=10)
    design_seed: int | None = None
    html_only: bool = False
    credential_ids: list[str] | None = None
    browser_enabled: bool | None = Field(None, description="Enable web research agent for topic inputs")
    browser_max_pages: int | None = Field(None, ge=1, le=20, description="Max pages to fetch (1-20)")
    output_format: Literal["pdf", "pptx"] = "pdf"


class RenderJsonBody(RenderOptions):
    """Exactly one of `text` or `structured` should be supplied."""

    text: str | None = Field(None, description="Raw document text")
    structured: dict[str, Any] | None = Field(
        None,
        description="Dict serialized to JSON for the pipeline",
    )

    @model_validator(mode="after")
    def _one_input_source(self) -> "RenderJsonBody":
        has_t = self.text is not None and str(self.text).strip() != ""
        has_s = self.structured is not None
        if has_t == has_s:
            raise ValueError(
                "Provide exactly one of: non-empty text, or structured (JSON object)",
            )
        return self
