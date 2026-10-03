"""Runtime configuration, read from the environment once at import time."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    user = os.environ.get("POSTGRES_USER", "register")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    host = os.environ.get("POSTGRES_HOST", "db")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "register")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"


@dataclass(frozen=True)
class Settings:
    database_url: str
    base_url: str
    retention_days: int


def load_settings() -> Settings:
    return Settings(
        database_url=_database_url(),
        base_url=os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/"),
        retention_days=int(os.environ.get("RETENTION_DAYS", "730")),
    )


settings = load_settings()
