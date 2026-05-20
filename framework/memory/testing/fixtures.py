from __future__ import annotations

from typing import Any

from framework.memory.models import MemoryQuery, MemoryRecord
from framework.memory.runtime import MemoryRuntime
from framework.memory.stores import InMemoryMemoryStore


def memory_record_fixture(**overrides: Any) -> MemoryRecord:
    payload = {"content": "fixture memory", "refs": {"reference_id": "fixture"}}
    payload.update(overrides)
    return MemoryRecord(**payload)


def memory_query_fixture(**overrides: Any) -> MemoryQuery:
    payload = {"query": "fixture"}
    payload.update(overrides)
    return MemoryQuery.from_dict(payload)


def memory_runtime_fixture(records: list[MemoryRecord] | None = None) -> MemoryRuntime:
    return MemoryRuntime(InMemoryMemoryStore(records))
