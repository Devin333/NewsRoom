from __future__ import annotations

from collections import Counter

import pytest

from business.research.domain import GateResult, ReaderIssue, SourceLineage
from business.research.domain.document import ResearchDocument
from business.research.reader import ReaderPayloadBuilder
from business.research.reader_repair import (
    ReaderRepairGateSuite,
    ReaderRepairPreconditionError,
    ReaderRepairService,
)
from tests.business.research.fakes import FakeResearchSourceProvider


@pytest.mark.parametrize(
    ("failure_point", "gate_name", "expected_stage", "expected_read_calls"),
    (
        pytest.param(
            "memory_query",
            "RepairRAGNamespaceGate",
            "memory_access",
            0,
            id="namespace",
        ),
        pytest.param(
            "rag_policy",
            "RepairRAGBudgetGate",
            "memory_access",
            0,
            id="memory-policy",
        ),
        pytest.param(
            "repair_case",
            "ReaderRepairSkillMutationGate",
            "memory_write",
            2,
            id="publication-policy",
        ),
        pytest.param(
            "memory_write_candidate",
            "ReaderRepairMemoryPolicyGate",
            "memory_write",
            2,
            id="memory-write-policy",
        ),
    ),
)
def test_failed_policy_precondition_never_writes_memory(
    failure_point: str,
    gate_name: str,
    expected_stage: str,
    expected_read_calls: int,
) -> None:
    memory = _CountingRepairMemory()
    service = ReaderRepairService(
        memory=memory,
        gates=_FailingPreconditionGates(failure_point, gate_name),
    )

    with pytest.raises(ReaderRepairPreconditionError) as raised:
        service.repair_reader_payload(
            payload=_repairable_payload(),
            run_id=f"repair-precondition-{failure_point}",
        )

    assert raised.value.stage == expected_stage
    assert raised.value.failed_gate_names == (gate_name,)
    assert memory.read_calls == expected_read_calls
    assert memory.write_calls == 0


def test_missing_source_lineage_fails_before_any_memory_call() -> None:
    memory = _CountingRepairMemory()
    issue = ReaderIssue(
        issue_id="issue-missing-lineage",
        paper_id="paper-harness-001",
        run_id="repair-missing-lineage",
        issue_type="source_lineage_missing",
        error_signature="source-lineage-missing",
        symptom="Reader payload has no source refs.",
        source_refs=[],
        payload_ref="reader-payload://paper-harness-001",
    )
    service = ReaderRepairService(
        memory=memory,
        issue_detector=_StaticIssueDetector(issue),
    )

    with pytest.raises(ReaderRepairPreconditionError) as raised:
        service.repair_reader_payload(
            payload=_repairable_payload(),
            run_id="repair-missing-lineage",
        )

    assert raised.value.stage == "source_lineage"
    assert raised.value.failed_gate_names == ("RepairRAGSourceLineageGate",)
    assert memory.read_calls == 0
    assert memory.write_calls == 0


def test_failed_candidate_is_recorded_only_after_preconditions_pass() -> None:
    memory = _CountingRepairMemory()
    service = ReaderRepairService(memory=memory)

    result = service.repair_reader_payload(
        payload=_repairable_payload(),
        run_id="repair-diagnostic-candidate",
        candidate_payload={
            "repair_summary": "Rejected candidate requests a memory write.",
            "promote_skill": True,
            "target_region_refs": ["paper://paper-harness-001/raw"],
            "patch_operations": [
                {
                    "op": "replace_region",
                    "path": "reader-payload://paper-harness-001",
                    "write_memory": True,
                }
            ],
        },
        repaired_payload_ref="artifact://unverified-reader-payload",
    )

    candidate_gate = next(
        gate
        for gate in result.gate_results
        if gate["gate_name"] == "ReaderRepairCandidateSchemaGate" and not gate["passed"]
    )
    assert result.successful is False
    assert set(candidate_gate["metadata"]["forbidden"]) == {"promote_skill", "write_memory"}
    assert result.repair_case.metadata["memory_record_kind"] == "failed_repair_diagnostic"
    assert result.repair_case.metadata["memory_preconditions_passed"] is True
    assert result.repair_result.payload_after_ref is None
    assert result.repair_case.payload_after_ref is None
    assert memory.calls["propose_write"] == 1
    assert memory.calls["write_case"] == 1
    assert memory.calls["write_strategy"] == 0


def test_unauthorized_memory_write_namespace_fails_before_proposal() -> None:
    memory = _CountingRepairMemory()
    service = ReaderRepairService(memory=memory)
    service.memory_service.namespace = "research.unauthorized"

    with pytest.raises(ReaderRepairPreconditionError) as raised:
        service.repair_reader_payload(
            payload=_repairable_payload(),
            run_id="repair-unauthorized-write-namespace",
        )

    assert raised.value.stage == "memory_write"
    assert raised.value.failed_gate_names == ("ReaderRepairMemoryPolicyGate",)
    assert memory.read_calls == 2
    assert memory.write_calls == 0


def _repairable_payload():
    paper = FakeResearchSourceProvider().paper
    document = ResearchDocument(
        paper_id=paper.paper_id,
        source_hash="sha256-reader-repair-side-effect",
        sections=[],
        lineage=SourceLineage(source_refs=["paper://paper-harness-001/raw"]),
    )
    return ReaderPayloadBuilder().build(paper=paper, document=document)


class _StaticIssueDetector:
    def __init__(self, issue: ReaderIssue) -> None:
        self._issue = issue

    def detect(self, *_args, **_kwargs):
        return [self._issue]


class _FailingPreconditionGates(ReaderRepairGateSuite):
    def __init__(self, failure_point: str, gate_name: str) -> None:
        self._failure_point = failure_point
        self._gate_name = gate_name

    def verify_memory_query(self, query):
        if self._failure_point == "memory_query":
            return [GateResult.fail(self._gate_name, "injected namespace failure")]
        return super().verify_memory_query(query)

    def verify_rag_policy(self, policy):
        if self._failure_point == "rag_policy":
            return [GateResult.fail(self._gate_name, "injected memory policy failure")]
        return super().verify_rag_policy(policy)

    def verify_case(self, repair_case):
        if self._failure_point == "repair_case":
            return [GateResult.fail(self._gate_name, "injected publication policy failure")]
        return super().verify_case(repair_case)

    def verify_memory_write_candidate(self, candidate):
        if self._failure_point == "memory_write_candidate":
            return [GateResult.fail(self._gate_name, "injected memory write policy failure")]
        return super().verify_memory_write_candidate(candidate)


class _CountingRepairMemory:
    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()
        self._cases = {}

    @property
    def read_calls(self) -> int:
        return sum(self.calls[name] for name in ("recall_cases", "recall_strategies", "list_cases"))

    @property
    def write_calls(self) -> int:
        return sum(self.calls[name] for name in ("propose_write", "write_case", "write_strategy"))

    def propose_write(self, candidate):
        self.calls["propose_write"] += 1
        return candidate

    def write_case(self, repair_case, *, namespace):
        self.calls["write_case"] += 1
        self._cases[repair_case.repair_case_id] = repair_case
        return f"memory://{namespace}/case/{repair_case.repair_case_id}"

    def write_strategy(self, strategy, *, namespace):
        self.calls["write_strategy"] += 1
        return f"memory://{namespace}/strategy/{strategy.strategy_id}"

    def recall_cases(self, query):
        self.calls["recall_cases"] += 1
        return tuple(self._cases.values())

    def recall_strategies(self, issue_type, *, namespace):
        self.calls["recall_strategies"] += 1
        return []

    def list_cases(self, *, namespace):
        self.calls["list_cases"] += 1
        return tuple(self._cases.values())

    def list_case_versions(self, repair_case_id, *, namespace):
        return ()

    def rollback_case(self, repair_case_id, *, namespace, version):
        raise KeyError(repair_case_id)

    def list_strategy_versions(self, strategy_id, *, namespace):
        return ()

    def rollback_strategy(self, strategy_id, *, namespace, version):
        raise KeyError(strategy_id)
