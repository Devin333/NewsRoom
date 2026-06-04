from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ResearchCandidateWorkerPort(Protocol):
    def generate_candidate(self, *, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        ...


__all__ = ["ResearchCandidateWorkerPort"]
