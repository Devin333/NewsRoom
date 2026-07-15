from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from framework.events.ports import EventStorePort
from infrastructure.storage.events.sqlite import SQLiteEventStore


DEFAULT_ARTIFACT_ROOT = Path(".newsroom/runs")
LOCAL_EVENT_DATABASE = Path("_records/events.sqlite3")


def event_store_from_env(
    *,
    artifact_root: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> EventStorePort:
    """Compose the canonical durable event store without silent fallback.

    A non-empty ``NEWS_DATABASE_DSN`` selects the shared PostgreSQL adapter.
    Otherwise a file-backed, single-host SQLite store is created below the
    configured artifact root.  Legacy JSONL stores are intentionally absent
    from this production composition boundary and remain explicit migration,
    import, and export adapters only.
    """

    values = env if env is not None else os.environ
    dsn = str(values.get("NEWS_DATABASE_DSN") or "").strip()
    if dsn:
        from infrastructure.storage.events.postgres import PostgresDurableEventStore

        return PostgresDurableEventStore(dsn)

    configured_root_value = str(values.get("NEWS_ARTIFACT_ROOT") or "").strip()
    configured_root = (
        Path(artifact_root)
        if artifact_root is not None
        else Path(configured_root_value or DEFAULT_ARTIFACT_ROOT)
    )
    return SQLiteEventStore(configured_root / LOCAL_EVENT_DATABASE)


__all__ = [
    "DEFAULT_ARTIFACT_ROOT",
    "LOCAL_EVENT_DATABASE",
    "event_store_from_env",
]
