from __future__ import annotations

import logging
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

# Repository root must be on path for orchestrator, agents, config.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi import FastAPI, Request, Response
from starlette.middleware.cors import CORSMiddleware

from app.api.api_v1.api import router as api_v1_router
from app.core.config import get_settings
from app.core.logging_config import configure_logging
from app.db.session import init_db

_audit = logging.getLogger("pdf_pipeline.audit")
logger = logging.getLogger("pdf_pipeline.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    configure_logging(log_file=s.log_file_resolved())

    if s.is_jwt_insecure():
        logger.warning(
            "JWT_SECRET is using the insecure default. "
            "Set JWT_SECRET in fastapi-app/.env before going to production. "
            'Generate: python -c "import secrets; print(secrets.token_hex(32))"'
        )
    if s.is_fernet_missing():
        logger.warning(
            "FERNET_KEY is not set — LLM key encryption/storage will be unavailable. "
            "Generate: python -c "
            '"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )

    init_db()
    s.storage_root_resolved().mkdir(parents=True, exist_ok=True)
    logger.info("PDF Pipeline API started (storage: %s)", s.storage_root_resolved())
    yield
    logger.info("PDF Pipeline API shutting down")


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


@app.middleware("http")
async def audit_middleware(request: Request, call_next) -> Response:
    start = time.perf_counter()
    response: Response = await call_next(request)
    elapsed_ms = int((time.perf_counter() - start) * 1000)

    # Extract user id from Authorization header for audit log (no DB lookup needed)
    user_hint = "-"
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:]
        try:
            from app.core.security import parse_user_id
            user_hint = parse_user_id(token)[:8]  # first 8 chars of UUID
        except Exception:
            user_hint = "invalid"

    _audit.info(
        "%s %s %s user=%s %dms",
        request.method,
        request.url.path,
        response.status_code,
        user_hint,
        elapsed_ms,
    )
    return response


app.include_router(api_v1_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
