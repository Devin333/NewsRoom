from __future__ import annotations

from datetime import UTC, datetime

from framework.events.canonical import checksum_for
from framework.harness import (
    HarnessGraphTerminalFailureContext,
    HarnessNodeOutputResourceIdentity,
    InMemoryHarnessEventPort,
    InMemoryHarnessNodeOutputResource,
    InMemoryHarnessSideEffectStore,
)
from framework.harness.graph.canonical import thaw_json

from business.research.application.reader_repair_runtime import (
    ReaderRepairGraphApplicationService,
    ReaderRepairGraphRequest,
)
from business.research.graphs.reader_repair import (
    READER_REPAIR_APPLICATION_OUTPUT_KEY,
    READER_REPAIR_APPLICATION_STEP_ID,
)
from business.research.ports.repair_memory import (
    ReaderRepairMemoryCommitReceipt,
    ReaderRepairMemoryCommitRequest,
    reader_repair_case_memory_ref,
    reader_repair_strategy_memory_ref,
)
from business.research.ports.reader_repair_candidate import (
    READER_REPAIR_PATCH_CANDIDATE_TASK,
)
from business.research.ports.reader_repair_failure_diagnostic import (
    ReaderRepairFailureDiagnosticCommitReceipt,
)
from business.research.reader_repair import InMemoryReaderRepairMemory
from infrastructure.research.reader_repair_memory_side_effect import (
    ReaderRepairMemorySideEffectHandler,
)
from infrastructure.research.reader_repair_failure_diagnostic_side_effect import (
    ReaderRepairFailureDiagnosticSideEffectHandler,
)
from tests.business.research.graphs.test_reader_repair_function_workers import (
    _ReaderRepairCandidateWorker,
    _payload,
)


class _AtomicMemoryCommitPort:
    """Observable idempotent double for the real terminal memory handler."""

    def __init__(self) -> None:
        self.requests: list[ReaderRepairMemoryCommitRequest] = []
        self.physical_commits = 0
        self._requests_by_idempotency: dict[str, ReaderRepairMemoryCommitRequest] = {}
        self._receipts_by_idempotency: dict[str, ReaderRepairMemoryCommitReceipt] = {}

    def commit(
        self,
        request: ReaderRepairMemoryCommitRequest,
    ) -> ReaderRepairMemoryCommitReceipt:
        self.requests.append(request)
        existing = self._receipts_by_idempotency.get(request.idempotency_key)
        if existing is not None:
            assert self._requests_by_idempotency[request.idempotency_key] == request
            return existing

        self.physical_commits += 1
        projection = request.projection
        receipt = ReaderRepairMemoryCommitReceipt(
            receipt_id=f"reader-repair-memory-receipt:{request.request_id}",
            request_ref=request.checksum,
            run_id=request.run_id,
            terminal_effect_id=request.terminal_effect_id,
            authorization_ref=request.authorization_ref,
            idempotency_key=request.idempotency_key,
            namespace=projection.candidate.namespace,
            case_ref=reader_repair_case_memory_ref(
                projection.repair_case,
                version=1,
            ),
            case_version=1,
            strategy_refs=tuple(
                reader_repair_strategy_memory_ref(strategy, version=1)
                for strategy in projection.strategies
            ),
            strategy_versions=tuple(1 for _strategy in projection.strategies),
            committed_at=datetime(2026, 8, 24, 12, 0, tzinfo=UTC),
        )
        self._requests_by_idempotency[request.idempotency_key] = request
        self._receipts_by_idempotency[request.idempotency_key] = receipt
        return receipt


class _NoopFailureDiagnosticHandler:
    """The successful path must not invoke the terminal-failure handler."""

    def __init__(self) -> None:
        self.calls = 0

    def commit(self, intent: object, authorization: object) -> tuple[object, object]:
        self.calls += 1
        return intent, authorization


class _TamperedLineageFailureDiagnosticHandler:
    """Inject an invalid observation binding before the real handler validates it."""

    def __init__(self, delegate: ReaderRepairFailureDiagnosticSideEffectHandler) -> None:
        self._delegate = delegate

    def build_terminal_failure_candidate(self, record, context):
        raw_context = thaw_json(context.outputs)
        outputs = dict(raw_context["by_output_key"])
        observation_slot = outputs["reader_repair_application_observation"]
        observation = dict(
            observation_slot["reader_repair_application_observation"]
            if "reader_repair_application_observation" in observation_slot
            else observation_slot
        )
        bindings = dict(observation["input_bindings"])
        bindings["reader_repair_application_candidate"] = checksum_for(
            {"tampered": True}
        )
        observation["input_bindings"] = bindings
        outputs["reader_repair_application_observation"] = {
            "reader_repair_application_observation": observation
        }
        tampered_context = HarnessGraphTerminalFailureContext(
            inputs=context.inputs,
            outputs={**raw_context, "by_output_key": outputs},
            failed_gate_evidence_refs=context.failed_gate_evidence_refs,
        )
        return self._delegate.build_terminal_failure_candidate(
            record,
            tampered_context,
        )

    def commit(self, intent, authorization):
        return self._delegate.commit(intent, authorization)


class _FailureDiagnosticCommitPort:
    def __init__(self) -> None:
        self.requests = []
        self.physical_commits = 0
        self._receipts = {}

    def commit_failure_diagnostic(self, request):
        self.requests.append(request)
        existing = self._receipts.get(request.idempotency_key)
        if existing is not None:
            return existing
        self.physical_commits += 1
        receipt = ReaderRepairFailureDiagnosticCommitReceipt(
            receipt_id=f"reader-repair-diagnostic-receipt:{request.request_id}",
            request_ref=request.checksum,
            run_id=request.run_id,
            terminal_effect_id=request.terminal_effect_id,
            authorization_ref=request.authorization_ref,
            idempotency_key=request.idempotency_key,
            namespace="research.reader_repair",
            diagnostic_case_ref=(
                "memory://research.reader_repair/diagnostic/"
                f"{request.candidate.repair_case.repair_case_id}"
            ),
            diagnostic_case_version=1,
            terminal_failure_record_ref=(
                request.candidate.terminal_failure.record_checksum
            ),
            committed_at=datetime(2026, 8, 24, 12, 0, tzinfo=UTC),
        )
        self._receipts[request.idempotency_key] = receipt
        return receipt


class _InvalidNavigationCandidateWorker(_ReaderRepairCandidateWorker):
    def generate_candidate(self, *, task, payload):
        proposal = super().generate_candidate(task=task, payload=payload)
        if task == READER_REPAIR_PATCH_CANDIDATE_TASK:
            for operation in proposal["patch_operations"]:
                if operation["op"] == "replace_navigation":
                    operation["replacement"] = []
        return proposal


def test_reader_repair_application_service_runs_physical_graph_and_recovers() -> None:
    event_port = InMemoryHarnessEventPort()
    node_output_resource = InMemoryHarnessNodeOutputResource()
    side_effect_store = InMemoryHarnessSideEffectStore()
    memory_commit_port = _AtomicMemoryCommitPort()
    memory_handler = ReaderRepairMemorySideEffectHandler(
        commit_port=memory_commit_port,
        side_effect_store=side_effect_store,
    )
    failure_handler = _NoopFailureDiagnosticHandler()
    candidate_worker = _ReaderRepairCandidateWorker()
    service = ReaderRepairGraphApplicationService(
        event_port_factory=lambda _run_id: event_port,
        node_output_resource=node_output_resource,
        side_effect_store=side_effect_store,
        memory=InMemoryReaderRepairMemory(),
        memory_side_effect_handler=memory_handler,
        failure_diagnostic_side_effect_handler=failure_handler,
        candidate_worker=candidate_worker,
    )
    request = ReaderRepairGraphRequest(
        run_id="reader-repair-application-service-run",
        reader_payload=_payload(),
        tenant_id="tenant-reader-repair-test",
        user_id="user-reader-repair-test",
        created_at=datetime(2026, 8, 24, 11, 0, tzinfo=UTC),
    )

    first = service.repair(request)

    assert first.succeeded
    recovery = event_port.recover_graph(request.run_id)
    activities = tuple(
        activity for activity in recovery.activities if activity.run_id == request.run_id
    )
    assert {activity.node_id for activity in activities} == {
        "detect_reader_issue",
        "assemble_repair_context",
        "propose_repair_candidate",
        "apply_repair_candidate",
        "collect_repair_application_observation",
        "verify_repair_application",
        "build_repair_result",
        "build_repair_case",
        "prepare_skill_candidate_bundle",
        "prepare_memory_write",
    }
    assert len(activities) == 10
    assert len(recovery.activity_result_commits) == 10
    assert len(candidate_worker.calls) == 2
    assert memory_handler.prepare_calls == 1
    assert memory_handler.commit_calls == 1
    assert memory_commit_port.physical_commits == 1
    assert len(memory_commit_port.requests) == 1
    assert failure_handler.calls == 0

    application_activity = next(
        activity
        for activity in activities
        if activity.node_id == READER_REPAIR_APPLICATION_STEP_ID
    )
    committed = node_output_resource.committed_output(
        HarnessNodeOutputResourceIdentity.for_activity(application_activity)
    )
    assert committed is not None
    application_result = first.worker_results[application_activity.node_instance_id]
    assert committed.candidate.output_refs == {
        READER_REPAIR_APPLICATION_OUTPUT_KEY: checksum_for(application_result.output)
    }

    second = service.repair(request)

    assert second.succeeded
    assert len(candidate_worker.calls) == 2
    assert len(event_port.recover_graph(request.run_id).activities) == 10
    assert memory_commit_port.physical_commits == 1
    assert len(memory_commit_port.requests) == 1
    assert failure_handler.calls == 0


def test_reader_repair_failed_verification_commits_quarantined_diagnostic_once() -> None:
    event_port = InMemoryHarnessEventPort()
    node_output_resource = InMemoryHarnessNodeOutputResource()
    side_effect_store = InMemoryHarnessSideEffectStore()
    memory_commit_port = _AtomicMemoryCommitPort()
    diagnostic_port = _FailureDiagnosticCommitPort()
    candidate_worker = _InvalidNavigationCandidateWorker()
    service = ReaderRepairGraphApplicationService(
        event_port_factory=lambda _run_id: event_port,
        node_output_resource=node_output_resource,
        side_effect_store=side_effect_store,
        memory=InMemoryReaderRepairMemory(),
        memory_side_effect_handler=ReaderRepairMemorySideEffectHandler(
            commit_port=memory_commit_port,
            side_effect_store=side_effect_store,
        ),
        failure_diagnostic_side_effect_handler=(
            ReaderRepairFailureDiagnosticSideEffectHandler(diagnostic_port)
        ),
        candidate_worker=candidate_worker,
    )
    request = ReaderRepairGraphRequest(
        run_id="reader-repair-failed-verification-run",
        reader_payload=_payload(),
        created_at=datetime(2026, 8, 24, 11, 0, tzinfo=UTC),
    )

    first = service.repair(request)

    assert not first.succeeded
    assert first.status == "halted"
    assert memory_commit_port.physical_commits == 0
    assert diagnostic_port.physical_commits == 1
    assert len(diagnostic_port.requests) == 1
    diagnostic = diagnostic_port.requests[0].candidate
    assert diagnostic.repair_case.successful is False
    assert diagnostic.repair_case.payload_after_ref is None
    assert diagnostic.repair_case.failure_reason
    assert diagnostic.failed_gate_evidence_refs
    assert diagnostic.repair_case.metadata["active_skill_mutation"] is False
    worker_calls = len(candidate_worker.calls)

    second = service.repair(request)

    assert not second.succeeded
    assert len(candidate_worker.calls) == worker_calls
    assert diagnostic_port.physical_commits == 1
    assert len(diagnostic_port.requests) == 1


def test_reader_repair_failure_diagnostic_rejects_mixed_lineage() -> None:
    event_port = InMemoryHarnessEventPort()
    node_output_resource = InMemoryHarnessNodeOutputResource()
    side_effect_store = InMemoryHarnessSideEffectStore()
    diagnostic_port = _FailureDiagnosticCommitPort()
    delegate = ReaderRepairFailureDiagnosticSideEffectHandler(diagnostic_port)
    service = ReaderRepairGraphApplicationService(
        event_port_factory=lambda _run_id: event_port,
        node_output_resource=node_output_resource,
        side_effect_store=side_effect_store,
        memory=InMemoryReaderRepairMemory(),
        memory_side_effect_handler=ReaderRepairMemorySideEffectHandler(
            commit_port=_AtomicMemoryCommitPort(),
            side_effect_store=side_effect_store,
        ),
        failure_diagnostic_side_effect_handler=_TamperedLineageFailureDiagnosticHandler(
            delegate
        ),
        candidate_worker=_InvalidNavigationCandidateWorker(),
    )
    request = ReaderRepairGraphRequest(
        run_id="reader-repair-mixed-lineage-run",
        reader_payload=_payload(),
        created_at=datetime(2026, 8, 24, 11, 0, tzinfo=UTC),
    )

    result = service.repair(request)

    assert not result.succeeded
    assert result.status == "halted"
    assert diagnostic_port.physical_commits == 0
    assert diagnostic_port.requests == []
