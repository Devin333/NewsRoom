from __future__ import annotations

from framework.memory.models import MemoryRecord
from framework.shared.json import json_loads, stable_json_dumps


class MemoryJsonSerializer:
    def dumps_record(self, record: MemoryRecord) -> str:
        return stable_json_dumps(record.to_dict())

    def loads_record(self, text: str) -> MemoryRecord:
        return MemoryRecord.from_dict(json_loads(text))

    def dumps_records(self, records: list[MemoryRecord]) -> str:
        return stable_json_dumps([record.to_dict() for record in records])

    def loads_records(self, text: str) -> list[MemoryRecord]:
        return [MemoryRecord.from_dict(item) for item in json_loads(text)]
