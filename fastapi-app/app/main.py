from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Repository root (parent of `fastapi-app/`) must be on path for orchestrator, agents, config.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.api.api_v1.api import router as api_v1_router
from app.core.config import get_settings
from app.core.logging_config import configure_logging
from app.db.session import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    init_db()
    get_settings().storage_root_resolved().mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title="PDF Pipeline API",
    version="1.0.0",
    lifespan=lifespan,
)

_settings = get_settings()
_origins = _settings.cors_origins_list()
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_v1_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
