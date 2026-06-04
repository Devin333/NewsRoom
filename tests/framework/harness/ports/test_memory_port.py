from __future__ import annotations

from framework.harness import FakeMemoryPort, MemoryWriteCandidate, MemoryWriteStatus


def test_memory_candidate_is_not_committed_until_harness_approves() -> None:
    memory = FakeMemoryPort()
    candidate = MemoryWriteCandidate(
        candidate_id="memory-candidate-1",
        namespace="research.reader",
        content={"repair": "prefer source refs"},
        source_refs=("evidence:1",),
    )

    proposed = memory.propose_write(candidate)

    assert proposed.status == MemoryWriteStatus.PROPOSED
    assert memory.committed == {}

    committed = memory.commit_write(proposed)

    assert committed.status == MemoryWriteStatus.COMMITTED
    assert memory.committed["memory-candidate-1"].content["repair"] == "prefer source refs"
