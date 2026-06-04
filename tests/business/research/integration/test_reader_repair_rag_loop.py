from __future__ import annotations

from business.research.domain import SourceLineage
from business.research.domain.document import ResearchDocument
from business.research.reader import ReaderPayloadBuilder
from business.research.reader_repair import InMemoryReaderRepairMemory, ReaderRepairService
from tests.business.research.fakes import FakeResearchSourceProvider


def test_reader_repair_loop_writes_memory_and_never_publishes_skill() -> None:
    paper = FakeResearchSourceProvider().paper
    document = ResearchDocument(
        paper_id=paper.paper_id,
        source_hash="sha256-reader-repair",
        sections=[],
        lineage=SourceLineage(source_refs=["paper://paper-harness-001/raw"]),
    )
    payload = ReaderPayloadBuilder().build(paper=paper, document=document)
    memory = InMemoryReaderRepairMemory()
    service = ReaderRepairService(memory=memory)

    result = service.repair_reader_payload(
        payload=payload,
        run_id="repair-run-integration",
        candidate_payload={
            "repair_summary": "Restore section navigation from source outline.",
            "target_region_refs": ["paper://paper-harness-001/raw"],
            "patch_operations": [{"op": "replace_region", "path": payload.payload_id}],
            "expected_effect": "Reader payload has source-backed navigation.",
        },
    )

    assert result.memory_ref.startswith("memory://research.reader_repair/case/")
    assert result.context_snapshot_ref
    assert result.skill_promotion_triggered is False
    assert result.repair_case.metadata["active_skill_mutation"] is False
    assert memory.cases[result.repair_case.repair_case_id].memory_kind == "episodic"


def test_reader_repair_loop_records_failed_candidate_in_memory() -> None:
    paper = FakeResearchSourceProvider().paper
    document = ResearchDocument(
        paper_id=paper.paper_id,
        source_hash="sha256-reader-repair",
        sections=[],
        lineage=SourceLineage(source_refs=["paper://paper-harness-001/raw"]),
    )
    payload = ReaderPayloadBuilder().build(paper=paper, document=document)
    service = ReaderRepairService(memory=InMemoryReaderRepairMemory())

    result = service.repair_reader_payload(
        payload=payload,
        run_id="repair-run-failed",
        candidate_payload={
            "repair_summary": "Bad candidate tries to decide workflow.",
            "target_region_refs": ["paper://paper-harness-001/raw"],
            "patch_operations": [{"op": "replace_region", "path": payload.payload_id, "write_memory": True}],
            "expected_effect": "This should be rejected by gates.",
            "promote_skill": True,
        },
    )

    assert result.successful is False
    assert result.repair_case.successful is False
    assert any(gate["gate_name"] == "ReaderRepairCandidateSchemaGate" and not gate["passed"] for gate in result.gate_results)
    assert result.skill_promotion_triggered is False
