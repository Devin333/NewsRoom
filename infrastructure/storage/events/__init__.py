"""Durable event adapters and explicitly legacy JSONL compatibility types."""

from typing import TYPE_CHECKING, Any

from infrastructure.storage.events.factory import event_store_from_env
from infrastructure.storage.events.local_json import LocalJsonEventStore
from infrastructure.storage.events.models import EventRecord
from infrastructure.storage.events.sqlite import SQLiteEventStore, SQLiteEventUnitOfWork

if TYPE_CHECKING:
    from infrastructure.storage.events.postgres import (
        PostgresDurableEventStore,
        PostgresEventUnitOfWork,
    )


def __getattr__(name: str) -> Any:
    """Load the optional PostgreSQL adapter only when explicitly requested."""

    if name in {"PostgresDurableEventStore", "PostgresEventUnitOfWork"}:
        from infrastructure.storage.events.postgres import (
            PostgresDurableEventStore,
            PostgresEventUnitOfWork,
        )

        return {
            "PostgresDurableEventStore": PostgresDurableEventStore,
            "PostgresEventUnitOfWork": PostgresEventUnitOfWork,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "EventRecord",
    "LocalJsonEventStore",
    "PostgresDurableEventStore",
    "PostgresEventUnitOfWork",
    "SQLiteEventStore",
    "SQLiteEventUnitOfWork",
    "event_store_from_env",
]
