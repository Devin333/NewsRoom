from __future__ import annotations

from backend.research.domain import SourceLineage
from backend.research.domain.document import ResearchDocument
from backend.research.reader import ReaderPayloadBuilder
from backend.research.reader_repair import InMemoryReaderRepairMemory, ReaderRepairService
from tests.backend.research.fakes import FakeResearchSourceProvider


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


def test_reader_repair_loop_uses_memory_port_case_listing_for_consolidation() -> None:
    paper = FakeResearchSourceProvider().paper
    document = ResearchDocument(
        paper_id=paper.paper_id,
        source_hash="sha256-reader-repair",
        sections=[],
        lineage=SourceLineage(source_refs=["paper://paper-harness-001/raw"]),
    )
    payload = ReaderPayloadBuilder().build(paper=paper, document=document)
    memory = _PortOnlyRepairMemory()
    service = ReaderRepairService(memory=memory)

    result = service.repair_reader_payload(
        payload=payload,
        run_id="repair-run-port-only",
        candidate_payload={
            "repair_summary": "Restore reader navigation from source lineage.",
            "target_region_refs": ["paper://paper-harness-001/raw"],
            "patch_operations": [{"op": "replace_region", "path": payload.payload_id}],
            "expected_effect": "Reader payload has source-backed navigation.",
        },
    )

    assert result.memory_ref.startswith("memory://research.reader_repair/case/")
    assert memory.list_cases_called is True


class _PortOnlyRepairMemory:
    def __init__(self) -> None:
        self._cases = {}
        self.written_strategies = []
        self.list_cases_called = False

    def write_case(self, repair_case, *, namespace):
        self._cases[repair_case.repair_case_id] = repair_case
        return f"memory://{namespace}/case/{repair_case.repair_case_id}"

    def recall_cases(self, query):
        return tuple(self._cases.values())

    def write_strategy(self, strategy, *, namespace):
        self.written_strategies.append((namespace, strategy))
        return f"memory://{namespace}/strategy/{strategy.strategy_id}"

    def recall_strategies(self, issue_type, *, namespace):
        return []

    def list_cases(self, *, namespace):
        self.list_cases_called = True
        return tuple(self._cases.values())

    def list_case_versions(self, repair_case_id, *, namespace):
        return ()

    def rollback_case(self, repair_case_id, *, namespace, version):
        raise KeyError(repair_case_id)

    def list_strategy_versions(self, strategy_id, *, namespace):
        return ()

    def rollback_strategy(self, strategy_id, *, namespace, version):
        raise KeyError(strategy_id)

    def propose_write(self, candidate):
        return candidate
