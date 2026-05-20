from __future__ import annotations

import os
from typing import Any


def source_health_store_from_env() -> Any | None:
    dsn = os.environ.get("NEWS_DATABASE_DSN")
    if not dsn:
        return None
    # TODO(boundary-migration): switch to infrastructure.storage.postgres after storage migration.
    from infrastructure.storage.postgres import PostgresRepository

    repository = PostgresRepository(dsn)
    repository.migrate()
    return repository


__all__ = ["source_health_store_from_env"]
