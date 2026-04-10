from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_repo_root() -> Path:
    # fastapi-app/app/core/config.py -> parents[3] = repository root (parent of fastapi-app/)
    return Path(__file__).resolve().parents[3]


def _fastapi_app_root() -> Path:
    return Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_fastapi_app_root() / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    repo_root: Path = Field(default_factory=_default_repo_root, alias="REPO_ROOT")
    fernet_key: str | None = Field(default=None, alias="FERNET_KEY")
    jwt_secret: str = Field(
        default="dev-insecure-change-me-use-long-random-string",
        alias="JWT_SECRET",
    )
    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    storage_root: Path | None = Field(default=None, alias="STORAGE_ROOT")
    access_token_expire_minutes: int = Field(
        default=60 * 24 * 7,
        alias="ACCESS_TOKEN_EXPIRE_MINUTES",
    )

    def database_url_resolved(self) -> str:
        if self.database_url:
            return self.database_url
        sqlite_path = self.repo_root / "data" / "api.sqlite3"
        return f"sqlite:///{sqlite_path.as_posix()}"

    def storage_root_resolved(self) -> Path:
        if self.storage_root is not None:
            return Path(self.storage_root)
        return self.repo_root / "data" / "storage"


@lru_cache
def get_settings() -> Settings:
    return Settings()
