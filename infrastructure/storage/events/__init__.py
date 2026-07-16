"""Durable event adapters and explicitly legacy JSONL compatibility types."""

from typing import TYPE_CHECKING, Any

from infrastructure.storage.events.factory import (
    DurableEventStorage,
    durable_event_storage_from_env,
    event_store_from_env,
)
from infrastructure.storage.events.activity_store import SQLiteRecordedActivityStore
from infrastructure.storage.events.local_json import LocalJsonEventStore
from infrastructure.storage.events.models import EventRecord
from infrastructure.storage.events.replay_checkpoints import SQLiteReplayCheckpointStore
from infrastructure.storage.events.sqlite import SQLiteEventStore, SQLiteEventUnitOfWork

if TYPE_CHECKING:
    from infrastructure.storage.events.activity_store import PostgresRecordedActivityStore
    from infrastructure.storage.events.replay_checkpoints import (
        PostgresReplayCheckpointStore,
    )
    from infrastructure.storage.events.postgres import (
        PostgresDurableEventStore,
        PostgresEventUnitOfWork,
    )


def __getattr__(name: str) -> Any:
    """Load the optional PostgreSQL adapter only when explicitly requested."""

    if name == "PostgresReplayCheckpointStore":
        from infrastructure.storage.events.replay_checkpoints import (
            PostgresReplayCheckpointStore,
        )

        return PostgresReplayCheckpointStore
    if name == "PostgresRecordedActivityStore":
        from infrastructure.storage.events.activity_store import PostgresRecordedActivityStore

        return PostgresRecordedActivityStore
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
    "DurableEventStorage",
    "EventRecord",
    "LocalJsonEventStore",
    "PostgresDurableEventStore",
    "PostgresEventUnitOfWork",
    "PostgresReplayCheckpointStore",
    "PostgresRecordedActivityStore",
    "SQLiteEventStore",
    "SQLiteEventUnitOfWork",
    "SQLiteReplayCheckpointStore",
    "SQLiteRecordedActivityStore",
    "durable_event_storage_from_env",
    "event_store_from_env",
]
