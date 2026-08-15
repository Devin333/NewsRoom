from __future__ import annotations

from framework.harness import FakeMemoryPort, MemoryWriteCandidate, MemoryWriteStatus


def test_memory_port_exposes_candidate_only_write_surface() -> None:
    memory = FakeMemoryPort()
    candidate = MemoryWriteCandidate(
        candidate_id="memory-candidate-1",
        namespace="research.reader",
        content={"repair": "prefer source refs"},
        source_refs=("evidence:1",),
    )

    proposed = memory.propose_write(candidate)

    assert proposed.status == MemoryWriteStatus.PROPOSED
    assert memory.proposed["memory-candidate-1"].content["repair"] == "prefer source refs"
    assert not hasattr(memory, "commit_write")
