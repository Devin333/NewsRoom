from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from framework.events.canonical import checksum_for
from framework.harness.memory import MemoryWriteCandidate

from backend.research.domain import (
    ReaderIssue,
    ReaderRepairCase,
    ReaderRepairSkillCandidateSeed,
    ReaderRepairStrategy,
)
from backend.research.graphs import (
    READER_REPAIR_MEMORY_STEP_ID,
    build_reader_repair_context_graph_identity,
    build_reader_repair_memory_worker_result,
)
from backend.research.ports import (
    ReaderRepairMemoryCommitPort,
    ReaderRepairMemoryCommitRequest,
)
from infrastructure.storage.postgres.repair_memory_repository import (
    PostgresReaderRepairMemoryCommitRecord,
)
from interfaces.services.reader_repair_memory import (
    PostgresReaderRepairMemoryCommitPort,
    PostgresReaderRepairMemoryPort,
)
from tests.backend.research.reader_repair._fixtures import make_repair_case


COMMITTED_AT = datetime(2026, 8, 16, 9, 30, tzinfo=UTC)
IDENTITY_SCOPE = checksum_for({"tenant_id": "tenant-a", "user_id": "user-a"})
SUBJECT_SCOPE = checksum_for({"paper_id": "paper-1"})


class _PayloadRepository:
    def __init__(self):
        self.calls = []
        self.payload = None

    def write_object(self, **kwargs):
        self.calls.append(("write_object", kwargs))
        self.payload = kwargs["payload"]
        return f"memory://{kwargs['namespace']}/{kwargs['object_type']}/{kwargs['object_id']}"

    def recall_case_payloads(self, **kwargs):
        self.calls.append(("recall_case_payloads", kwargs))
        return (self.payload,)

    def recall_strategy_payloads(self, **kwargs):
        self.calls.append(("recall_strategy_payloads", kwargs))
        return (self.payload,)

    def list_case_payloads(self, **kwargs):
        self.calls.append(("list_case_payloads", kwargs))
        return (self.payload,)

    def list_versions(self, **kwargs):
        self.calls.append(("list_versions", kwargs))
        return ()

    def version_payload(self, **kwargs):
        self.calls.append(("version_payload", kwargs))
        return self.payload


class _CommitRepository:
    def __init__(self) -> None:
        self.calls = []
        self.record = None

    def commit_bundle(self, **kwargs):
        self.calls.append(kwargs)
        return self.record


def test_postgres_reader_repair_memory_port_maps_case_domain_models() -> None:
    issue = _issue()
    case = make_repair_case("case-1", issue=issue, successful=True)
    repository = _PayloadRepository()
    port = PostgresReaderRepairMemoryPort(repository)

    ref = port.write_case(case)
    recalled = port.recall_cases(port_query(issue))

    assert ref == "memory://research.reader_repair/case/case-1"
    assert recalled[0].repair_case_id == "case-1"
    write_call = repository.calls[0][1]
    assert write_call["object_type"] == "case"
    assert write_call["error_signature"] == issue.error_signature


def test_postgres_reader_repair_memory_port_rolls_back_strategy_from_payload_version() -> None:
    strategy = ReaderRepairStrategy(
        strategy_id="strategy-1",
        issue_type="table_parse_error",
        applicability="Repeated table parse repair.",
        steps=["match table signature", "restore cells", "verify lineage"],
        confidence=0.9,
        source_case_refs=["case-1"],
        status="promoted_memory",
    )
    repository = _PayloadRepository()
    repository.payload = strategy.to_dict()
    port = PostgresReaderRepairMemoryPort(repository)

    ref = port.rollback_strategy("strategy-1", version=1)

    assert ref == "memory://research.reader_repair/strategy/strategy-1"
    assert repository.calls[-1][1]["operation"] == "rollback"


def test_postgres_reader_repair_memory_commit_port_maps_atomic_bundle() -> None:
    request = _commit_request()
    repository = _CommitRepository()
    repository.record = _commit_record(request, case_version=2, strategy_version=3)
    port = PostgresReaderRepairMemoryCommitPort(repository)

    receipt = port.commit(request)

    call = repository.calls[0]
    assert isinstance(port, ReaderRepairMemoryCommitPort)
    assert call["request_checksum"] == request.checksum
    assert call["namespace"] == "research.reader_repair"
    assert call["repair_case"].object_type == "case"
    assert call["repair_case"].object_id == "repair-case-1"
    assert call["repair_case"].operation == "harness_commit"
    assert call["repair_case"].payload["repair_case_id"] == "repair-case-1"
    assert tuple(item.object_id for item in call["strategies"]) == (
        "repair-strategy-1",
    )
    assert receipt.request_ref == request.checksum
    assert receipt.case_ref == (
        "memory://research.reader_repair/case/repair-case-1/versions/2"
    )
    assert receipt.strategy_refs == (
        "memory://research.reader_repair/strategy/repair-strategy-1/versions/3",
    )
    assert receipt.strategy_versions == (3,)
    assert receipt.committed_at == COMMITTED_AT
    assert receipt.checksum is not None


def test_postgres_reader_repair_memory_commit_port_returns_stable_receipt() -> None:
    request = _commit_request()
    repository = _CommitRepository()
    repository.record = _commit_record(request, case_version=2, strategy_version=3)
    port = PostgresReaderRepairMemoryCommitPort(repository)

    first = port.commit(request)
    second = port.commit(request)

    assert first == second
    assert len(repository.calls) == 2


def test_postgres_reader_repair_memory_commit_port_rejects_conflicting_record() -> None:
    request = _commit_request()
    repository = _CommitRepository()
    repository.record = replace(
        _commit_record(request, case_version=2, strategy_version=3),
        run_id="another-run",
    )
    port = PostgresReaderRepairMemoryCommitPort(repository)

    with pytest.raises(ValueError, match="record conflicts"):
        port.commit(request)


def test_postgres_reader_repair_memory_commit_port_rejects_invalid_record() -> None:
    request = _commit_request()
    repository = _CommitRepository()
    repository.record = {"request_checksum": request.checksum}
    port = PostgresReaderRepairMemoryCommitPort(repository)

    with pytest.raises(TypeError, match="invalid record"):
        port.commit(request)


def _commit_request() -> ReaderRepairMemoryCommitRequest:
    repair_case = _commit_case()
    graph_identity = build_reader_repair_context_graph_identity(
        run_id="repair-run-1",
        stage_id=READER_REPAIR_MEMORY_STEP_ID,
    )
    strategy = ReaderRepairStrategy(
        strategy_id="repair-strategy-1",
        issue_type=repair_case.issue.issue_type,
        applicability="Repeated source-backed section boundary failures.",
        steps=["match signature", "patch region", "verify source lineage"],
        confidence=0.9,
        source_case_refs=[repair_case.repair_case_id],
        status="promoted_memory",
    )
    seed = ReaderRepairSkillCandidateSeed(
        seed_id="repair-seed-1",
        strategy=strategy,
        experience_refs=[f"repair-case://{repair_case.repair_case_id}"],
        patch_objective="Prepare governed reader-repair skill candidate input.",
        publishes_skill=False,
        metadata={"requires_harness_skill_evolution": True},
    )
    strategy_bundle = {
        "input_bindings": {
            "reader_repair_context_pack": checksum_for({"context": "verified"}),
            "reader_repair_case": checksum_for(repair_case.to_dict()),
        },
        "strategies": [strategy.to_dict()],
        "skill_candidate_seeds": [seed.to_dict()],
    }
    result = build_reader_repair_memory_worker_result(
        run_id="repair-run-1",
        repair_case=repair_case,
        strategy_candidate_bundle=strategy_bundle,
        identity_scope_ref=IDENTITY_SCOPE,
        subject_scope_ref=SUBJECT_SCOPE,
        graph_id=graph_identity.graph_id,
        graph_version=graph_identity.graph_version,
        graph_ref=graph_identity.graph_ref,
        graph_checksum=graph_identity.graph_checksum,
        node_id=graph_identity.stage_id,
        node_instance_id=f"{graph_identity.stage_id}:1",
        activity_id=graph_identity.stage_id,
    )
    raw_candidate = result.output["memory_write_candidate"]
    candidate = MemoryWriteCandidate(
        candidate_id=raw_candidate["candidate_id"],
        namespace=raw_candidate["namespace"],
        content=raw_candidate["content"],
        source_refs=tuple(raw_candidate["source_refs"]),
        status=raw_candidate["status"],
        metadata=raw_candidate["metadata"],
    )
    assert result.effect_intent is not None
    return ReaderRepairMemoryCommitRequest(
        request_id="reader-repair-memory-commit:request-1",
        run_id="repair-run-1",
        terminal_effect_id="reader-repair-memory-terminal:repair-run-1",
        candidate=candidate,
        candidate_checksum=result.effect_intent.payload[
            "memory_candidate_checksum"
        ],
        prepared_outcome_ref=checksum_for({"prepared": "outcome"}),
        authorization_ref=checksum_for({"authorization": "terminal"}),
        identity_scope_ref=IDENTITY_SCOPE,
        subject_scope_ref=SUBJECT_SCOPE,
        atomic_group="reader-repair-memory:repair-run-1",
        idempotency_key="reader-repair-memory-idempotency-1",
    )


def _commit_case() -> ReaderRepairCase:
    issue = ReaderIssue(
        issue_id="reader-issue-1",
        paper_id="paper-1",
        run_id="repair-run-1",
        issue_type="section_boundary_error",
        error_signature="section-boundary:paper-1",
        symptom="A section boundary is missing.",
        source_refs=["paper://paper-1/section-1"],
        payload_ref="reader-payload://paper-1",
    )
    return ReaderRepairCase(
        repair_case_id="repair-case-1",
        issue=issue,
        repair_strategy="Restore the source-backed section boundary.",
        successful=True,
        verification_results=[
            {"gate_name": "ReaderRepairResultGate", "passed": True}
        ],
        payload_before_ref="reader-payload://paper-1",
        payload_after_ref="reader-payload://paper-1/repaired",
        source_refs=issue.source_refs,
        metadata={"active_skill_mutation": False},
    )


def _commit_record(
    request: ReaderRepairMemoryCommitRequest,
    *,
    case_version: int,
    strategy_version: int,
) -> PostgresReaderRepairMemoryCommitRecord:
    assert request.checksum is not None
    return PostgresReaderRepairMemoryCommitRecord(
        idempotency_key=request.idempotency_key,
        request_checksum=request.checksum,
        request_id=request.request_id,
        run_id=request.run_id,
        terminal_effect_id=request.terminal_effect_id,
        authorization_ref=request.authorization_ref,
        identity_scope_ref=request.identity_scope_ref,
        subject_scope_ref=request.subject_scope_ref,
        namespace=request.candidate.namespace,
        case_object_id="repair-case-1",
        case_version=case_version,
        strategy_versions=(("repair-strategy-1", strategy_version),),
        committed_at=COMMITTED_AT,
    )


def _issue() -> ReaderIssue:
    return ReaderIssue(
        issue_id="issue-table",
        paper_id="paper-1",
        issue_type="table_parse_error",
        error_signature="table_parse_error:build_reader_payload:pdf:missing_cells",
        symptom="Table dropped cells.",
        source_refs=["paper://paper-1/table-1"],
        payload_ref="reader-payload-1",
    )


def port_query(issue: ReaderIssue):
    from backend.research.domain.reader_repair import ReaderRepairMemoryQuery

    return ReaderRepairMemoryQuery.from_issue(issue, source_format="pdf")
