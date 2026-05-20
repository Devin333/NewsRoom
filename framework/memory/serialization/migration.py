from __future__ import annotations

from typing import Any, Protocol


class MemorySchemaMigration(Protocol):
    source_version: str
    target_version: str

    def migrate(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...


class MemoryMigrationRegistry:
    def __init__(self) -> None:
        self._migrations: dict[tuple[str, str], MemorySchemaMigration] = {}

    def register(self, migration: MemorySchemaMigration) -> None:
        self._migrations[(migration.source_version, migration.target_version)] = migration

    def migrate(self, payload: dict[str, Any], *, target_version: str) -> dict[str, Any]:
        current = str(payload.get("schema_version") or "1")
        if current == target_version:
            return dict(payload)
        migration = self._migrations[(current, target_version)]
        return migration.migrate(dict(payload))
