from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from framework.events.canonical import checksum_for
from framework.harness import (
    HarnessAdmittedGraphActivityOutputAdapter,
    HarnessCommittedNodeOutputInputResolver,
    HarnessGraphActivity,
    HarnessGraphReference,
    HarnessNodeOutputCandidate,
    HarnessValidationError,
    HarnessWorkerResult,
    HarnessWorkerStatus,
    InMemoryHarnessNodeOutputResource,
)
from framework.harness.graph import (
    HarnessContractKind,
    HarnessContractReference,
    HarnessWorkerType,
)
from framework.harness.graph.bindings import HarnessActivityCapabilities
from framework.harness.graph.versioning import (
    HARNESS_CONDITION_POLICY_VERSION,
    HARNESS_GRAPH_COMPILER_VERSION,
    NORMALIZED_HARNESS_GRAPH_SCHEMA,
)
from framework.shared.attempts import AttemptSupervisor

from business.research.domain import (
    ReaderIssue,
    ReaderNavigationItem,
    ReaderRepairApplicationCandidate,
    ReaderRepairApplicationObservationCandidate,
    ReaderRepairCase,
    ReaderRepairContextPack,
    ReaderRepairPatchCandidate,
    ResearchDocument,
    ResearchSection,
    SourceLineage,
    research_subject_scope_ref,
    stable_research_id,
)
from business.research.graphs.reader_repair import (
    READER_REPAIR_APPLICATION_OUTPUT_KEY,
    READER_REPAIR_APPLICATION_STEP_ID,
    READER_REPAIR_COMMITTED_OUTPUT_BINDING_ID,
    READER_REPAIR_GRAPH_ID,
    READER_REPAIR_GRAPH_VERSION,
    READER_REPAIR_SUBAGENT_IDS,
    build_reader_repair_graph_definition,
)
from business.research.graphs.reader_repair_execution_gates import (
    READER_REPAIR_EXECUTION_GATE_REFERENCES,
)
from business.research.graphs.reader_repair_function_workers import (
    ReaderRepairRunAuthorityContext,
    build_reader_repair_function_worker_implementations,
)
from business.research.graphs.reader_repair_runtime import (
    build_reader_repair_runtime_binding_bundle,
)
from business.research.reader import ReaderPayloadBuilder
from business.research.reader_repair import (
    InMemoryReaderRepairMemory,
    ReaderRepairIssueDetector,
    apply_reader_repair_candidate,
    reader_repair_component_checksum,
    verify_reader_repair_application,
)
from tests.business.research.fakes import FakeResearchSourceProvider


_RUN_ID = "reader-repair-function-run"
_SOURCE_REF = "paper://paper-harness-001/raw"
_NOW = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)
_IDENTITY_SCOPE_REF = checksum_for({"identity": "reader-repair-test"})
_EXECUTION_ORDER = (
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
)


@dataclass(frozen=True, slots=True)
class _RunAuthorityResolver:
    context: ReaderRepairRunAuthorityContext

    def resolve(self, *, run_id: str) -> ReaderRepairRunAuthorityContext:
        return self.context


class _DurableApplicationReceiptResolver:
    def __init__(self) -> None:
        self.definition = build_reader_repair_graph_definition()
        self.resource = InMemoryHarnessNodeOutputResource()
        self.resolver = HarnessCommittedNodeOutputInputResolver(
            resource=self.resource
        )
        self.activity = _application_activity(self.definition)
        self._committed = False

    def commit(self, application: ReaderRepairApplicationCandidate) -> None:
        if self._committed:
            return
        HarnessAdmittedGraphActivityOutputAdapter(
            resource=self.resource,
            supervisor=AttemptSupervisor(),
            clock=lambda: _NOW,
        ).run(
            lambda: HarnessNodeOutputCandidate(
                output_refs={
                    READER_REPAIR_APPLICATION_OUTPUT_KEY: checksum_for(
                        application.to_dict()
                    )
                },
                evidence_refs=(checksum_for({"source_ref": _SOURCE_REF}),),
            ),
            activity=self.activity,
            timeout_seconds=None,
            attempt_id="reader-repair-physical-attempt-1",
        )
        self._committed = True

    def resolve(
        self,
        *,
        definition,
        run_id: str,
        application: ReaderRepairApplicationCandidate,
    ):
        assert run_id
        return self.resolver.resolve(
            definition=definition,
            binding_id=READER_REPAIR_COMMITTED_OUTPUT_BINDING_ID,
            producer_activity=self.activity,
            payload=application.to_dict(),
        )


@dataclass(frozen=True, slots=True)
class _SubAgentWorker:
    worker_id: str
    worker_version: str
    worker_type: HarnessWorkerType = HarnessWorkerType.SUBAGENT

    def execute(self, _task: dict[str, Any]) -> HarnessWorkerResult:
        raise AssertionError("candidate outputs are supplied explicitly in this test")


@dataclass(frozen=True, slots=True)
class _Activity:
    activity_contract_id: str
    activity_contract_version: str
    capabilities: HarnessActivityCapabilities = HarnessActivityCapabilities(
        stable_idempotency=True
    )

    def dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        return dict(request)


class _MemorySideEffectHandler:
    def prepare(self, intent: object, authorization: object) -> tuple[object, object]:
        return intent, authorization

    def commit(self, intent: object, authorization: object) -> tuple[object, object]:
        return intent, authorization


def test_reader_repair_function_workers_execute_the_verified_chain_without_activation() -> None:
    payload = _payload()
    memory = InMemoryReaderRepairMemory()
    authority = _authority(payload.paper.paper_id)
    receipt_resolver = _DurableApplicationReceiptResolver()
    function_workers = build_reader_repair_function_worker_implementations(
        memory=memory,
        run_authority_resolver=_RunAuthorityResolver(authority),
        committed_output_resolver=receipt_resolver,
    )
    definition = build_reader_repair_graph_definition()
    worker_implementations = dict(function_workers)
    activity_implementations: dict[str, object] = {}
    for step_id in _EXECUTION_ORDER:
        activity = definition.activity(step_id)
        assert activity is not None
        leaf = definition.leaf_activity_binding(activity.step_id)
        assert leaf is not None
        if activity.step_id in READER_REPAIR_SUBAGENT_IDS:
            worker_implementations[activity.step_id] = _SubAgentWorker(
                worker_id=leaf.worker_ref.contract_id,
                worker_version=leaf.worker_ref.version,
            )
        activity_implementations[activity.step_id] = _Activity(
            activity_contract_id=leaf.activity_ref.contract_id,
            activity_contract_version=leaf.activity_ref.version,
        )
    bundle = build_reader_repair_runtime_binding_bundle(
        worker_implementations=worker_implementations,
        activity_implementations=activity_implementations,
        memory_side_effect_handler=_MemorySideEffectHandler(),
    )

    outputs: dict[str, Any] = {}
    worker_results: dict[str, HarnessWorkerResult] = {}
    tasks: dict[str, dict[str, Any]] = {}
    gate_results = []
    for step_id in _EXECUTION_ORDER:
        activity = definition.activity(step_id)
        assert activity is not None
        if activity.step_id == "propose_repair_candidate":
            context_pack = ReaderRepairContextPack.model_validate(
                outputs["reader_repair_context_pack"]
            )
            result = HarnessWorkerResult(
                status=HarnessWorkerStatus.SUCCEEDED,
                output={
                    "reader_repair_patch_candidate": _candidate(
                        payload,
                        context_pack,
                    ).to_dict()
                },
            )
        elif activity.step_id == "collect_repair_application_observation":
            candidate = ReaderRepairPatchCandidate.model_validate(
                outputs["reader_repair_patch_candidate"]
            )
            application = ReaderRepairApplicationCandidate.model_validate(
                outputs[READER_REPAIR_APPLICATION_OUTPUT_KEY]
            )
            result = HarnessWorkerResult(
                status=HarnessWorkerStatus.SUCCEEDED,
                output={
                    "reader_repair_application_observation": _observation(
                        candidate,
                        application,
                    ).to_dict()
                },
            )
        else:
            task = _task(definition, activity.step_id, payload, outputs)
            tasks[activity.step_id] = task
            result = function_workers[activity.step_id].execute(task)
        worker_results[activity.step_id] = result
        assert result.status is HarnessWorkerStatus.SUCCEEDED

        gate = bundle.authority.resolve_gate(activity.quality_gate)[-1].gate
        gate_result = gate.evaluate(
            _gate_context(result, prior=outputs, payload=payload)
        )
        gate_results.append(gate_result)
        assert gate_result.passed, gate_result.to_dict()

        for key, value in result.output.items():
            outputs[key] = value
        if activity.step_id == "detect_reader_issue":
            memory.write_case(
                _prior_case(ReaderIssue.model_validate(outputs["reader_issue"])),
                namespace="research.reader_repair",
            )
        if activity.step_id == READER_REPAIR_APPLICATION_STEP_ID:
            receipt_resolver.commit(
                ReaderRepairApplicationCandidate.model_validate(
                    outputs[READER_REPAIR_APPLICATION_OUTPUT_KEY]
                )
            )

    assert set(function_workers) == {
        activity.step_id
        for activity in definition.activities
        if activity.worker_type is HarnessWorkerType.FUNCTION
    }
    assert len(gate_results) == 10
    assert all(item.passed for item in gate_results)
    assert set(READER_REPAIR_EXECUTION_GATE_REFERENCES).issubset(
        {activity.quality_gate for activity in definition.activities}
    )
    assert bundle.to_manifest()["installs_runtime_authority"] is False
    assert worker_results["prepare_memory_write"].effect_intent is not None
    assert str(worker_results["prepare_memory_write"].effect_intent.handler) == (
        "research.reader_repair.memory.commit@1"
    )
    assert len(memory.cases) == 1
    assert memory.write_candidates == {}
    assert "artifact_ref" not in outputs["reader_repair_result"]
    assert "public_ref" not in outputs["reader_repair_result"]

    for step_id in (
        "detect_reader_issue",
        "build_repair_case",
        "prepare_skill_candidate_bundle",
        "prepare_memory_write",
    ):
        replayed = function_workers[step_id].execute(tasks[step_id])
        assert replayed.to_dict() == worker_results[step_id].to_dict()


def test_reader_repair_function_workers_fail_closed_on_task_and_authority_substitution() -> None:
    payload = _payload()
    receipt_resolver = _DurableApplicationReceiptResolver()
    workers = build_reader_repair_function_worker_implementations(
        memory=InMemoryReaderRepairMemory(),
        run_authority_resolver=_RunAuthorityResolver(
            ReaderRepairRunAuthorityContext(
                run_id="other-run",
                paper_id=payload.paper.paper_id,
                created_at=_NOW,
                identity_scope_ref=_IDENTITY_SCOPE_REF,
                subject_scope_ref=research_subject_scope_ref(payload.paper.paper_id),
            )
        ),
        committed_output_resolver=receipt_resolver,
    )
    definition = build_reader_repair_graph_definition()
    task = _task(definition, "detect_reader_issue", payload, {})

    with pytest.raises(HarnessValidationError) as authority_error:
        workers["detect_reader_issue"].execute(task)

    assert authority_error.value.code == (
        "reader_repair_function_worker_contract_invalid"
    )

    missing_input = dict(task)
    missing_input["inputs"] = dict(task["inputs"])
    missing_input["inputs"].pop("run_id")
    with pytest.raises(HarnessValidationError) as input_error:
        workers["detect_reader_issue"].execute(missing_input)

    assert input_error.value.details["expected_input_keys"] == [
        "reader_payload",
        "run_id",
        "source_format",
    ]


def test_reader_repair_function_workers_reject_cross_run_receipts_and_unbound_memory_attempts() -> None:
    payload = _payload()
    receipt_resolver = _DurableApplicationReceiptResolver()
    workers = build_reader_repair_function_worker_implementations(
        memory=InMemoryReaderRepairMemory(),
        run_authority_resolver=_RunAuthorityResolver(
            _authority(payload.paper.paper_id)
        ),
        committed_output_resolver=receipt_resolver,
    )
    definition = build_reader_repair_graph_definition()
    issue = ReaderRepairIssueDetector().detect(
        payload,
        run_id=_RUN_ID,
        source_format="pdf",
        created_at=_NOW,
    )[0]
    context_pack = ReaderRepairContextPack(
        context_id="reader-repair-function-context",
        issue=issue,
        source_refs=issue.source_refs,
        source_lineage=SourceLineage(source_refs=issue.source_refs),
        failure_case_gap_report={"no_failed_cases_available": True},
    )
    candidate = _candidate(payload, context_pack)
    application = apply_reader_repair_candidate(
        payload=payload,
        candidate=candidate,
    )
    receipt_resolver.commit(application)
    other_issue = issue.model_copy(update={"run_id": "other-run"}, deep=True)
    observation = _observation(candidate, application)
    verification = verify_reader_repair_application(
        payload=payload,
        issue=other_issue,
        candidate=candidate,
        application=application,
        observation=observation,
    )
    result_task = _task(
        definition,
        "build_repair_result",
        payload,
        {
            "reader_issue": other_issue.to_dict(),
            "reader_repair_patch_candidate": candidate.to_dict(),
            "reader_repair_application_candidate": application.to_dict(),
            "reader_repair_application_observation": observation.to_dict(),
            "reader_repair_application_verification": verification.to_dict(),
        },
    )
    result_task["run_id"] = "other-run"

    with pytest.raises(HarnessValidationError) as receipt_error:
        workers["build_repair_result"].execute(result_task)

    assert receipt_error.value.code == (
        "reader_repair_function_worker_contract_invalid"
    )
    assert "another run" in str(receipt_error.value)

    repair_case = _prior_case(issue)
    strategy_bundle = {
        "input_bindings": {
            "reader_repair_context_pack": checksum_for(context_pack.to_dict()),
            "reader_repair_case": checksum_for(repair_case.to_dict()),
        },
        "strategies": [],
        "skill_candidate_seeds": [],
    }
    memory_task = _task(
        definition,
        "prepare_memory_write",
        payload,
        {
            "reader_repair_case": repair_case.to_dict(),
            "strategy_candidate_bundle": strategy_bundle,
        },
    )
    memory_task.pop("harness_activity")

    with pytest.raises(HarnessValidationError) as activity_error:
        workers["prepare_memory_write"].execute(memory_task)

    assert "requires a Harness activity attempt" in str(activity_error.value)


def test_reader_repair_run_authority_rejects_malformed_or_wrong_subject_scopes() -> None:
    paper_id = _payload().paper.paper_id

    with pytest.raises(ValueError, match="sha256 reference"):
        ReaderRepairRunAuthorityContext(
            run_id=_RUN_ID,
            paper_id=paper_id,
            created_at=_NOW,
            identity_scope_ref="identity",
            subject_scope_ref=research_subject_scope_ref(paper_id),
        )

    with pytest.raises(ValueError, match="does not match paper_id"):
        ReaderRepairRunAuthorityContext(
            run_id=_RUN_ID,
            paper_id=paper_id,
            created_at=_NOW,
            identity_scope_ref=_IDENTITY_SCOPE_REF,
            subject_scope_ref=checksum_for({"paper_id": "other-paper"}),
        )


def test_reader_repair_function_worker_module_stays_out_of_production_composition() -> None:
    module_source = Path(
        "business/research/graphs/reader_repair_function_workers.py"
    ).read_text(encoding="utf-8").casefold()
    production_sources = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in (
            "business/research/application/single_paper_runtime.py",
            "interfaces/composition/research.py",
            "business/research/graphs/__init__.py",
        )
    )

    assert "artifact" not in module_source
    assert "reader_repair_function_workers" not in production_sources
    assert "build_reader_repair_function_worker_implementations" not in (
        production_sources
    )


def _authority(paper_id: str) -> ReaderRepairRunAuthorityContext:
    return ReaderRepairRunAuthorityContext(
        run_id=_RUN_ID,
        paper_id=paper_id,
        created_at=_NOW,
        identity_scope_ref=_IDENTITY_SCOPE_REF,
        subject_scope_ref=research_subject_scope_ref(paper_id),
    )


def _task(definition, step_id: str, payload, outputs: dict[str, Any]):
    activity = definition.activity(step_id)
    assert activity is not None
    root_inputs = {
        "reader_payload": payload.to_dict(),
        "run_id": _RUN_ID,
        "source_format": "pdf",
    }
    inputs = {
        key: outputs[key] if key in outputs else root_inputs[key]
        for key in activity.input_keys
    }
    return {
        "run_id": _RUN_ID,
        "step_id": step_id,
        "worker_type": HarnessWorkerType.FUNCTION.value,
        "inputs": inputs,
        "metadata": dict(activity.metadata),
        "harness_activity": {
            "activity_id": f"activity-{step_id}-1",
            "idempotency_key": f"reader-repair:{step_id}:1",
            "attempt": 1,
            "contract_version": "1",
        },
    }


def _gate_context(
    worker_result: HarnessWorkerResult,
    *,
    prior: dict[str, Any],
    payload,
):
    return SimpleNamespace(
        worker_result=worker_result,
        state=SimpleNamespace(
            metadata={
                "outputs": {
                    key: {key: value}
                    for key, value in prior.items()
                }
            },
            run_spec=SimpleNamespace(
                inputs={
                    "reader_payload": payload.to_dict(),
                    "run_id": _RUN_ID,
                    "source_format": "pdf",
                }
            ),
        ),
    )


def _payload():
    paper = FakeResearchSourceProvider().paper
    document = ResearchDocument(
        paper_id=paper.paper_id,
        source_hash="sha256-reader-repair-function-workers",
        sections=[],
        lineage=SourceLineage(source_refs=[_SOURCE_REF]),
    )
    return ReaderPayloadBuilder().build(paper=paper, document=document)


def _candidate(
    payload,
    context_pack: ReaderRepairContextPack,
) -> ReaderRepairPatchCandidate:
    section = ResearchSection(
        section_id="section-1",
        title="Introduction",
        text="Source-backed introduction.",
        source_ref=_SOURCE_REF,
    )
    repaired_document = ResearchDocument(
        paper_id=payload.paper.paper_id,
        source_hash=payload.document.source_hash,
        sections=[section],
        lineage=payload.document.lineage,
    )
    navigation = ReaderNavigationItem(
        item_id=stable_research_id(
            "nav",
            payload.paper.paper_id,
            section.section_id,
        ),
        title=section.title,
        target_ref=section.section_id,
        order=0,
    )
    return ReaderRepairPatchCandidate(
        candidate_id="reader-repair-function-candidate",
        repair_summary="Restore the source-backed section and navigation.",
        target_region_refs=[_SOURCE_REF],
        patch_operations=[
            {
                "op": "replace_document",
                "operation_id": "replace-document",
                "expected_before_checksum": reader_repair_component_checksum(
                    payload,
                    "document",
                ),
                "source_refs": [_SOURCE_REF],
                "replacement": repaired_document,
            },
            {
                "op": "replace_navigation",
                "operation_id": "replace-navigation",
                "expected_before_checksum": reader_repair_component_checksum(
                    payload,
                    "navigation",
                ),
                "source_refs": [_SOURCE_REF],
                "replacement": [navigation],
            },
        ],
        expected_effect="Reader navigation matches the repaired document.",
        confidence=0.9,
        metadata={
            "input_bindings": {
                "reader_payload": checksum_for(payload.to_dict()),
                "reader_repair_context_pack": checksum_for(
                    context_pack.to_dict()
                ),
            }
        },
    )


def _observation(
    candidate: ReaderRepairPatchCandidate,
    application: ReaderRepairApplicationCandidate,
) -> ReaderRepairApplicationObservationCandidate:
    return ReaderRepairApplicationObservationCandidate(
        candidate_id=candidate.candidate_id,
        application_id=application.application_id,
        observations=[
            {
                "check_id": "source-backed-application",
                "finding": "The application is source-backed.",
                "evidence_refs": [_SOURCE_REF],
            }
        ],
        source_refs=[_SOURCE_REF],
        input_bindings={
            "reader_repair_patch_candidate": checksum_for(candidate.to_dict()),
            "reader_repair_application_candidate": checksum_for(
                application.to_dict()
            ),
        },
    )


def _prior_case(issue: ReaderIssue) -> ReaderRepairCase:
    return ReaderRepairCase(
        repair_case_id="reader-repair-prior-case",
        issue=issue,
        repair_strategy="Restore source-backed reader navigation.",
        repair_attempt_refs=["reader-repair-prior-attempt"],
        successful=True,
        verification_results=[
            {"gate_name": "ReaderRepairApplicationVerificationGate@1", "passed": True}
        ],
        payload_before_ref=issue.payload_ref or "reader-payload-before",
        payload_after_ref=checksum_for({"prior_payload": issue.issue_id}),
        source_refs=issue.source_refs,
        constraints=["preserve source lineage"],
        created_at=_NOW,
        metadata={
            "active_skill_mutation": False,
            "strategy_steps": [
                "match issue signature",
                "apply localized reader payload patch",
                "verify schema and source lineage",
            ],
        },
    )


def _application_activity(definition) -> HarnessGraphActivity:
    leaf = definition.leaf_activity_binding(READER_REPAIR_APPLICATION_STEP_ID)
    assert leaf is not None
    return HarnessGraphActivity(
        run_id=_RUN_ID,
        graph_ref=HarnessGraphReference(
            graph_id=READER_REPAIR_GRAPH_ID,
            workflow_ref=HarnessContractReference(
                HarnessContractKind.WORKFLOW,
                READER_REPAIR_GRAPH_ID,
                READER_REPAIR_GRAPH_VERSION,
            ),
            schema_version=NORMALIZED_HARNESS_GRAPH_SCHEMA,
            compiler_version=HARNESS_GRAPH_COMPILER_VERSION,
            condition_policy_version=HARNESS_CONDITION_POLICY_VERSION,
            checksum=checksum_for(
                {"graph": READER_REPAIR_GRAPH_ID, "version": "2"}
            ),
        ),
        node_id=READER_REPAIR_APPLICATION_STEP_ID,
        node_instance_id="reader-repair-application-node-instance-1",
        step_ref=HarnessContractReference(
            HarnessContractKind.STEP,
            f"research.reader_repair.{READER_REPAIR_APPLICATION_STEP_ID}",
            "1",
        ),
        worker_ref=leaf.worker_ref,
        activity_ref=leaf.activity_ref,
        attempt=1,
        input_ref=checksum_for({"input": "reader-repair-application"}),
        causal_decision_checksum=checksum_for(
            {"decision": "reader-repair-application"}
        ),
        causal_decision_sequence=1,
        fencing_generation=1,
        identity_scope_ref=_IDENTITY_SCOPE_REF,
        subject_scope_ref=research_subject_scope_ref(
            FakeResearchSourceProvider().paper.paper_id
        ),
    )
