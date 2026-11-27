"""Application settings.

Configuration (non-secret) lives in config.yaml; secrets come from the
environment. Keeping them separate means config is reviewable in git while
credentials never are.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.yaml"


def load_yaml_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Read the non-secret config file. Side-effecting; returns {} if absent."""
    if not path.exists():
        return {}
    with path.open() as fh:
        return yaml.safe_load(fh) or {}


class Settings(BaseSettings):
    """Secrets and environment-specific values."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str = "postgresql+psycopg://postgres:test@localhost:55432/gerry"

    anthropic_api_key: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    s3_bucket: str = "mr-gerry-media"
    s3_region: str = "us-west-1"

    log_level: str = "INFO"
    git_sha: str = Field(default="dev", description="Injected at build time")

    @field_validator("database_url")
    @classmethod
    def _normalise_driver(cls, v: str) -> str:
        """Accept the bare postgres:// scheme platforms hand out.

        Fly (and Heroku, and others) inject `postgres://...`, but SQLAlchemy
        needs an explicit driver. Normalising here is more robust than
        rewriting the platform's secret, which would drift on reattach.
        """
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+psycopg://", 1)
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+psycopg://", 1)
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
