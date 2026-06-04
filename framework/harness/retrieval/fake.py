from __future__ import annotations

from framework.harness.retrieval.evidence_pack import EvidencePack, EvidencePackCollection
from framework.harness.retrieval.request import RetrievalRequest


class FakeRetrievalPort:
    def __init__(self, packs: tuple[EvidencePack, ...] | None = None) -> None:
        self.packs = packs or (
            EvidencePack(
                evidence_id="evidence:fake:1",
                title="Fake source with verifiable references",
                summary="A deterministic fake evidence pack for Harness tests.",
                source_refs=("source://fake-paper#section=abstract", "citation://fake-paper#ref=1"),
                confidence=0.9,
                freshness="static-fixture",
                lineage=("retrieval.fake", "fixture.seed"),
                metadata={"section_refs": ["abstract"], "citation_refs": ["ref-1"]},
            ),
        )
        self.requests: list[RetrievalRequest] = []

    def retrieve(self, request: RetrievalRequest) -> EvidencePackCollection:
        self.requests.append(request)
        return EvidencePackCollection(
            packs=self.packs[: request.limit],
            request_ref=f"retrieval://fake/{len(self.requests)}",
            metadata={"query": request.query, "scope": request.scope},
        )


__all__ = ["FakeRetrievalPort"]
