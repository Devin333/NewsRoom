from __future__ import annotations

from framework.harness import EvidencePack, FakeRetrievalPort, RetrievalRequest
from framework.shared.json import stable_json_dumps


def test_evidence_pack_is_serializable_with_lineage_and_source_refs() -> None:
    pack = EvidencePack(
        evidence_id="evidence:1",
        title="A source",
        summary="Grounded evidence.",
        source_refs=("source://paper#section=intro",),
        confidence=0.8,
        freshness="2026-01-01",
        lineage=("retrieval.fake", "source.read"),
        metadata={"citation_refs": ["ref-1"]},
    )

    payload = pack.to_dict()
    assert payload["source_refs"] == ["source://paper#section=intro"]
    assert payload["lineage"] == ["retrieval.fake", "source.read"]
    assert stable_json_dumps(payload)


def test_fake_retrieval_port_returns_verifiable_source_refs() -> None:
    retrieval = FakeRetrievalPort()
    collection = retrieval.retrieve(RetrievalRequest(query="paper", limit=1))

    assert collection.packs[0].source_refs
    assert collection.packs[0].lineage
    assert collection.packs[0].metadata["section_refs"] == ["abstract"]
