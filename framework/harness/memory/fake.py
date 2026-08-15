from __future__ import annotations

from dataclasses import replace
from typing import Any

from framework.harness.memory.ports import MemoryWriteCandidate, MemoryWriteStatus


class FakeMemoryPort:
    def __init__(self, recalled: tuple[dict[str, Any], ...] = ()) -> None:
        self.recalled = tuple(dict(item) for item in recalled)
        self.proposed: dict[str, MemoryWriteCandidate] = {}
        self.recall_requests: list[dict[str, Any]] = []

    def recall(self, request: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        self.recall_requests.append(dict(request))
        return self.recalled

    def propose_write(self, candidate: MemoryWriteCandidate) -> MemoryWriteCandidate:
        proposed = replace(candidate, status=MemoryWriteStatus.PROPOSED)
        self.proposed[proposed.candidate_id] = proposed
        return proposed


__all__ = ["FakeMemoryPort"]
