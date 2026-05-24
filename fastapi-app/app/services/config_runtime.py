"""Snapshot / restore pipeline `config` module for per-request API overrides."""

from __future__ import annotations

import copy
from typing import Any

import config

_CONFIG_KEYS: tuple[str, ...] = (
    "PROVIDER",
    # Ollama / local Gemma 4
    "OLLAMA_BASE_URL",
    "OLLAMA_MODEL",
    "USE_LONG_CONTEXT",
    "GEMMA4_LONG_CONTEXT_CHARS",
    # OpenRouter
    "OPENROUTER_API_KEY",
    "OPENROUTER_API_KEYS",
    "OPENROUTER_SITE_URL",
    "OPENROUTER_SITE_NAME",
    # NVIDIA
    "NVIDIA_API_KEY",
    # Per-agent model overrides
    "MODEL_ANALYZER",
    "MODEL_PLANNER",
    "MODEL_DESIGNER",
    "MODEL_ASSEMBLER",
    "MODEL_CRITIC",
    # Gemini direct
    "GEMINI_KEY_1",
    "GEMINI_KEY_2",
    "GEMINI_KEY_3",
    "GEMINI_MODEL",
    # Pipeline behaviour
    "MAX_ITERATIONS",
    "PASS_THRESHOLD",
    "VISUAL_STYLE",
    "DESIGN_SEED",
    "MAX_DATA_CHARS",
    "BROWSER_ENABLED",
    "BROWSER_MAX_PAGES",
)


def _clone(val: Any) -> Any:
    if isinstance(val, list):
        return copy.copy(val)
    return val


def snapshot_config() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in _CONFIG_KEYS:
        if hasattr(config, k):
            out[k] = _clone(getattr(config, k))
    return out


def apply_runtime_config(overrides: dict[str, Any]) -> None:
    for k, v in overrides.items():
        if v is None:
            continue
        if k in _CONFIG_KEYS:
            setattr(config, k, v)


def restore_config(snap: dict[str, Any]) -> None:
    for k, v in snap.items():
        setattr(config, k, _clone(v))
