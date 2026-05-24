from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.crypto import decrypt_secret
from app.crud import preference as preference_crud
from app.models.llm_credential import LLMCredential
from app.models.preference import UserPreference
from app.models.user import User
from app.schemas.preferences import PreferencesBody
from app.schemas.render import AgentModels, RenderOptions


def _apply_model_fields(
    target: dict[str, Any],
    models: AgentModels | None,
    model_all: str | None,
) -> None:
    if model_all:
        for key in ("MODEL_ANALYZER", "MODEL_PLANNER", "MODEL_DESIGNER", "MODEL_ASSEMBLER", "MODEL_CRITIC"):
            target[key] = model_all
        return
    if not models:
        return
    m = models.model_dump(exclude_none=True)
    mapping = {
        "analyzer": "MODEL_ANALYZER",
        "planner": "MODEL_PLANNER",
        "designer": "MODEL_DESIGNER",
        "assembler": "MODEL_ASSEMBLER",
        "critic": "MODEL_CRITIC",
    }
    for small, big in mapping.items():
        if small in m:
            target[big] = m[small]


def _prefs_dict_to_runtime(settings: dict[str, Any] | None) -> dict[str, Any]:
    if not settings:
        return {}
    out: dict[str, Any] = {}
    if settings.get("provider"):
        out["PROVIDER"] = settings["provider"]
    _apply_model_fields(
        out,
        AgentModels.model_validate(settings["models"]) if settings.get("models") else None,
        settings.get("model_all"),
    )
    if settings.get("visual_style"):
        out["VISUAL_STYLE"] = settings["visual_style"]
    if settings.get("max_iterations") is not None:
        out["MAX_ITERATIONS"] = settings["max_iterations"]
    if settings.get("pass_threshold") is not None:
        out["PASS_THRESHOLD"] = settings["pass_threshold"]
    if settings.get("max_data_chars") is not None:
        out["MAX_DATA_CHARS"] = settings["max_data_chars"]
    return out


def _options_to_runtime(opts: RenderOptions | PreferencesBody) -> dict[str, Any]:
    d = opts.model_dump(exclude_none=True)
    out: dict[str, Any] = {}
    if "provider" in d:
        out["PROVIDER"] = d["provider"]
    models = AgentModels.model_validate(d["models"]) if d.get("models") else None
    _apply_model_fields(out, models, d.get("model_all"))
    if "visual_style" in d:
        out["VISUAL_STYLE"] = d["visual_style"]
    if "max_iterations" in d:
        out["MAX_ITERATIONS"] = d["max_iterations"]
    if "pass_threshold" in d:
        out["PASS_THRESHOLD"] = d["pass_threshold"]
    if "max_data_chars" in d:
        out["MAX_DATA_CHARS"] = d["max_data_chars"]
    if isinstance(opts, RenderOptions) and opts.design_seed is not None:
        out["DESIGN_SEED"] = opts.design_seed
    if isinstance(opts, RenderOptions) and opts.browser_enabled is not None:
        out["BROWSER_ENABLED"] = opts.browser_enabled
    if isinstance(opts, RenderOptions) and opts.browser_max_pages is not None:
        out["BROWSER_MAX_PAGES"] = opts.browser_max_pages
    return out


def merge_llm_keys_from_db(
    db: Session,
    user_id: str,
    provider: str,
    credential_ids: list[str] | None,
) -> dict[str, Any]:
    q = db.query(LLMCredential).filter(
        LLMCredential.user_id == user_id,
        LLMCredential.provider == provider,
    )
    if credential_ids:
        q = q.filter(LLMCredential.id.in_(credential_ids))
    rows = q.order_by(LLMCredential.created_at.asc()).all()
    if not rows:
        return {}

    keys = [decrypt_secret(r.secret_enc) for r in rows]
    out: dict[str, Any] = {}
    if provider == "ollama":
        # The stored "key" is the Ollama base URL (for remote/custom Ollama instances).
        # Local default (http://localhost:11434) needs no stored credential.
        out["OLLAMA_BASE_URL"] = keys[0]
    elif provider == "openrouter":
        out["OPENROUTER_API_KEY"] = keys[0]
        out["OPENROUTER_API_KEYS"] = keys
    elif provider == "gemini":
        out["GEMINI_KEY_1"] = keys[0]
        out["GEMINI_KEY_2"] = keys[1] if len(keys) > 1 else keys[0]
    elif provider == "nvidia":
        out["NVIDIA_API_KEY"] = keys[0]
    return out


def build_runtime_config(
    db: Session,
    user: User,
    job_options: RenderOptions | None,
) -> dict[str, Any]:
    prefs_row = db.query(UserPreference).filter(UserPreference.user_id == user.id).one_or_none()
    merged: dict[str, Any] = {}
    if prefs_row and prefs_row.settings_json:
        merged.update(_prefs_dict_to_runtime(prefs_row.settings_json))
    if job_options:
        merged.update(_options_to_runtime(job_options))

    prov = merged.get("PROVIDER")
    if not prov and prefs_row and prefs_row.settings_json:
        prov = prefs_row.settings_json.get("provider")

    cred_ids = job_options.credential_ids if job_options else None
    if prov:
        merged.update(merge_llm_keys_from_db(db, user.id, prov, cred_ids))
    return merged


def upsert_preferences(db: Session, user_id: str, body: PreferencesBody) -> dict[str, Any]:
    return preference_crud.upsert_merge(db, user_id, body)
