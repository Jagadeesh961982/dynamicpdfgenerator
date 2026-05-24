"""Ensure repository root is importable (orchestrator, agents, config)."""

from __future__ import annotations

import sys
from pathlib import Path

_FASTAPI_APP = Path(__file__).resolve().parents[2]
_REPO_ROOT = _FASTAPI_APP.parent
for p in (_REPO_ROOT, _FASTAPI_APP):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)
