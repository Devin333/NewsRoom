from __future__ import annotations

from framework.harness.memory import MemoryWriteCandidate, MemoryWriteStatus
from framework.memory import InMemoryMemoryStore, MemoryKind, MemoryRecord, MemoryRuntime, MemoryScope

from backend.research.rag.adapters import ResearchRAGMemoryPort


def test_research_rag_memory_port_maps_episodic_runtime_hits_by_namespace() -> None:
    runtime = MemoryRuntime(InMemoryMemoryStore([
        MemoryRecord(
            memory_id="mem-1",
            content="Prior paper ask found the ablation evidence in section 4.",
            kind=MemoryKind.EPISODIC,
        scope=MemoryScope.GRAPH,
            namespace="research.public",
            refs={"run_id": "run-1"},
        ),
        MemoryRecord(
            memory_id="mem-2",
            content="Private memory should not cross namespaces.",
            kind=MemoryKind.EPISODIC,
        scope=MemoryScope.GRAPH,
            namespace="research.private",
        ),
        MemoryRecord(
            memory_id="mem-3",
            content="Semantic memory is excluded from the first RAG memory slice.",
            kind=MemoryKind.SEMANTIC,
        scope=MemoryScope.GRAPH,
            namespace="research.public",
        ),
    ]))
    port = ResearchRAGMemoryPort(runtime)

    hits = port.recall({
        "query": "ablation evidence",
        "namespace": "research.public",
        "limit": 5,
    })

    assert [hit["memory_id"] for hit in hits] == ["mem-1"]
    assert hits[0]["namespace"] == "research.public"
    assert hits[0]["memory_ref"] == "memory://research.public/mem-1"
    assert hits[0]["content"].startswith("Prior paper ask")
    assert hits[0]["relevance"] > 0


def test_research_rag_memory_port_exposes_candidate_only_write_surface() -> None:
    store = InMemoryMemoryStore()
    runtime = MemoryRuntime(store)
    port = ResearchRAGMemoryPort(runtime)
    candidate = MemoryWriteCandidate(
        candidate_id="candidate-1",
        namespace="research.public",
        content={"memory": "do not write from normal RAG recall"},
    )

    proposed = port.propose_write(candidate)

    assert proposed.status == MemoryWriteStatus.PROPOSED
    assert not hasattr(port, "commit_write")
    assert store.records() == []
