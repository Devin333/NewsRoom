from __future__ import annotations

import json
from pathlib import Path

from infrastructure.storage.entities.models import EntityKind, TrackedEntity, TrackedEntityNotFoundError


ENTITY_STORE_SCHEMA_VERSION = "tracked_entity_store.v1"


class LocalJsonTrackedEntityStore:
    def __init__(self, path: str | Path = ".newsroom/entities/entities.json") -> None:
        self.path = Path(path)

    def list_entities(
        self,
        *,
        enabled_only: bool = False,
        kind: EntityKind | str | None = None,
    ) -> list[TrackedEntity]:
        records = sorted(self._read_records().values(), key=lambda item: item.entity_id)
        if enabled_only:
            records = [record for record in records if record.enabled]
        if kind is not None:
            actual_kind = EntityKind(kind)
            records = [record for record in records if record.kind == actual_kind]
        return records

    def get_entity(self, entity_id: str) -> TrackedEntity:
        records = self._read_records()
        try:
            return records[entity_id]
        except KeyError as exc:
            raise TrackedEntityNotFoundError(entity_id) from exc

    def upsert_entity(self, entity: TrackedEntity) -> TrackedEntity:
        records = self._read_records()
        records[entity.entity_id] = entity
        self._write_records(records)
        return entity

    def set_enabled(self, entity_id: str, *, enabled: bool) -> TrackedEntity:
        entity = self.get_entity(entity_id)
        updated = entity.with_enabled(enabled)
        self.upsert_entity(updated)
        return updated

    def delete_entity(self, entity_id: str) -> bool:
        records = self._read_records()
        if entity_id not in records:
            return False
        records.pop(entity_id)
        self._write_records(records)
        return True

    def _read_records(self) -> dict[str, TrackedEntity]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        entities = payload.get("entities", [])
        records = [TrackedEntity.from_dict(item) for item in entities]
        return {record.entity_id: record for record in records}

    def _write_records(self, records: dict[str, TrackedEntity]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": ENTITY_STORE_SCHEMA_VERSION,
            "entities": [record.to_dict() for record in sorted(records.values(), key=lambda item: item.entity_id)],
        }
        temp_path = self.path.with_name(f"{self.path.name}.tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp_path.replace(self.path)
