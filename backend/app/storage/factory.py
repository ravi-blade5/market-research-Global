from __future__ import annotations

from app.config import Settings
from app.storage.local_store import LocalRunStore
from app.storage.postgres_store import PostgresRunStore


def create_run_store(settings: Settings):
    backend = settings.run_store_backend.lower().strip()
    if backend in {"local", "json"}:
        return LocalRunStore(settings)
    if backend in {"postgres", "postgresql", "cloudsql", "cloud_sql"}:
        return PostgresRunStore(settings)
    raise ValueError(f"Unsupported RUN_STORE_BACKEND: {settings.run_store_backend}")
