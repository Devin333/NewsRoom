from __future__ import annotations

from typing import Protocol, runtime_checkable

from framework.harness.retrieval.evidence_pack import EvidencePackCollection
from framework.harness.retrieval.request import RetrievalRequest


@runtime_checkable
class RetrievalPort(Protocol):
    def retrieve(self, request: RetrievalRequest) -> EvidencePackCollection:
        ...


__all__ = ["RetrievalPort"]
