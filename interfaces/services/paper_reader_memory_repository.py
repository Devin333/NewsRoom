from __future__ import annotations

import os
from typing import Any


def paper_reader_memory_repository_from_env() -> Any | None:
    if os.environ.get("NEWS_MEMORY_POSTGRES_ENABLED", "").lower() not in {"1", "true", "yes", "on"}:
        return None
    dsn = os.environ.get("NEWS_DATABASE_DSN")
    if not dsn:
        return None
    from infrastructure.storage.postgres.memory_repository import PostgresIntelligenceMemoryRepository
    from infrastructure.storage.postgres.repository import PostgresRepository

    return PostgresIntelligenceMemoryRepository(PostgresRepository(dsn))
