from __future__ import annotations

from typing import Any, Protocol

from framework.memory.models import MemoryRecord


class MemoryProjector(Protocol):
    def project(self, value: Any) -> list[MemoryRecord]:
        ...


class DictMemoryProjector:
    def project(self, value: dict[str, Any] | str) -> list[MemoryRecord]:
        if isinstance(value, str):
            return [MemoryRecord(content=value)]
        payload = dict(value)
        content = str(payload.get("content") or payload.get("text") or "")
        return [MemoryRecord(content=content, metadata={key: item for key, item in payload.items() if key not in {"content", "text"}})]
