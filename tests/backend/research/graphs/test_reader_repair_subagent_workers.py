from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from framework.events.canonical import checksum_for
from framework.harness import HarnessValidationError, HarnessWorkerStatus
from framework.harness.graph import HarnessGraphCompiler, HarnessWorkerType
from framework.shared.graph_identity import GraphExecutionIdentity

from backend.research.domain import (
    ReaderNavigationItem,
    ReaderRepairApplicationCandidate,
    ReaderRepairApplicationObservationCandidate,
    ReaderRepairContextPack,
    ReaderRepairPatchCandidate,
    ResearchDocument,
    ResearchReaderPayload,
    ResearchSection,
    SourceLineage,
    stable_research_id,
)
from backend.research.graphs.reader_repair import (
    READER_REPAIR_SUBAGENT_IDS,
    build_reader_repair_graph_definition,
)
from backend.research.graphs.reader_repair_subagent_workers import (
    READER_REPAIR_APPLICATION_OBSERVATION_TASK,
    READER_REPAIR_PATCH_CANDIDATE_TASK,
    build_reader_repair_subagent_worker_implementations,
)
from backend.research.reader import ReaderPayloadBuilder
from backend.research.reader_repair import (
    ReaderRepairIssueDetector,
    apply_reader_repair_candidate,
    reader_repair_component_checksum,
)
from tests.backend.research.fakes import FakeResearchSourceProvider


_RUN_ID = "reader-repair-subagent-run"
_SOURCE_REF = "paper://paper-harness-001/raw"
_NOW = datetime(2026, 8, 16, 10, 0, tzinfo=UTC)


class _CandidateWorker:
    def __init__(self) -> None:
        self.patch_proposal: dict[str, Any] | None = None
        self.observation_proposal: dict[str, Any] | None = None
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.execution_identities: list[GraphExecutionIdentity | None] = []

    def generate_candidate(
        self,
        *,
        task: str,
        payload: dict[str, Any],
        execution_identity: GraphExecutionIdentity | None = None,
    ) -> dict[str, Any]:
        self.calls.append((task, deepcopy(payload)))
        self.execution_identities.append(execution_identity)
        if task == READER_REPAIR_PATCH_CANDIDATE_TASK:
            if self.patch_proposal is None:
                raise AssertionError("patch proposal was not configured")
            return deepcopy(self.patch_proposal)
        if task == READER_REPAIR_APPLICATION_OBSERVATION_TASK:
            if self.observation_proposal is None:
                raise AssertionError("observation proposal was not configured")
            return deepcopy(self.observation_proposal)
        raise AssertionError(f"unexpected candidate task: {task}")


def test_reader_repair_subagent_workers_bind_exact_graph_identity_and_inputs() -> None:
    candidate_worker = _CandidateWorker()
    workers = build_reader_repair_subagent_worker_implementations(
        candidate_worker=candidate_worker,
    )
    definition = build_reader_repair_graph_definition()

    assert set(workers) == set(READER_REPAIR_SUBAGENT_IDS)
    for step_id, worker in workers.items():
        activity = definition.activity(step_id)
        leaf = definition.leaf_activity_binding(step_id)
        assert activity is not None
        assert leaf is not None
        assert worker.worker_id == leaf.worker_ref.contract_id
        assert worker.worker_version == leaf.worker_ref.version
        assert worker.worker_type is HarnessWorkerType.SUBAGENT
        assert worker.input_keys == activity.input_keys
        assert worker.spec.subagent_id == READER_REPAIR_SUBAGENT_IDS[step_id]
        assert worker.spec.metadata["candidate_only"] is True


def test_reader_repair_subagents_enrich_candidates_without_llm_authority() -> None:
    payload, context_pack = _payload_and_context()
    candidate_worker = _CandidateWorker()
    candidate_worker.patch_proposal = _patch_proposal(payload)
    workers = build_reader_repair_subagent_worker_implementations(
        candidate_worker=candidate_worker,
    )
    definition = build_reader_repair_graph_definition()

    proposer_task = _task(
        definition,
        "propose_repair_candidate",
        {
            "reader_payload": payload.to_dict(),
            "reader_repair_context_pack": context_pack.to_dict(),
        },
    )
    first = workers["propose_repair_candidate"].execute(proposer_task)
    replayed = workers["propose_repair_candidate"].execute(proposer_task)
    candidate = ReaderRepairPatchCandidate.model_validate(
        first.output["reader_repair_patch_candidate"]
    )

    assert first.status is HarnessWorkerStatus.SUCCEEDED
    assert replayed.to_dict() == first.to_dict()
    assert candidate.metadata == {
        "candidate_only": True,
        "input_bindings": {
            "reader_payload": checksum_for(payload.to_dict()),
            "reader_repair_context_pack": checksum_for(context_pack.to_dict()),
        },
        "subagent_id": "reader_repair_proposer",
    }
    assert candidate.target_region_refs == [_SOURCE_REF]
    assert [operation.expected_before_checksum for operation in candidate.patch_operations] == [
        reader_repair_component_checksum(payload, "document"),
        reader_repair_component_checksum(payload, "navigation"),
    ]
    assert len({operation.operation_id for operation in candidate.patch_operations}) == 2

    application = apply_reader_repair_candidate(
        payload=payload,
        candidate=candidate,
    )
    candidate_worker.observation_proposal = {
        "observations": [
            {
                "check_id": "source-backed-application",
                "finding": "The candidate restored the cited source section.",
                "evidence_refs": [_SOURCE_REF],
            }
        ]
    }
    observation_result = workers[
        "collect_repair_application_observation"
    ].execute(
        _task(
            definition,
            "collect_repair_application_observation",
            {
                "reader_issue": context_pack.issue.to_dict(),
                "reader_repair_patch_candidate": candidate.to_dict(),
                "reader_repair_application_candidate": application.to_dict(),
            },
        )
    )
    observation = ReaderRepairApplicationObservationCandidate.model_validate(
        observation_result.output["reader_repair_application_observation"]
    )

    assert observation.candidate_id == candidate.candidate_id
    assert observation.application_id == application.application_id
    assert observation.source_refs == application.source_refs
    assert observation.input_bindings == {
        "reader_repair_patch_candidate": checksum_for(candidate.to_dict()),
        "reader_repair_application_candidate": checksum_for(
            application.to_dict()
        ),
    }
    assert observation.metadata == {
        "candidate_only": True,
        "deterministic_verdict": False,
        "subagent_id": "reader_repair_verifier",
    }
    assert [task for task, _payload in candidate_worker.calls] == [
        READER_REPAIR_PATCH_CANDIDATE_TASK,
        READER_REPAIR_PATCH_CANDIDATE_TASK,
        READER_REPAIR_APPLICATION_OBSERVATION_TASK,
    ]


def test_reader_repair_subagents_forward_physical_graph_identity() -> None:
    payload, context_pack = _payload_and_context()
    candidate_worker = _CandidateWorker()
    candidate_worker.patch_proposal = _patch_proposal(payload)
    candidate_worker.observation_proposal = {
        "observations": [
            {
                "check_id": "source-backed-application",
                "finding": "The candidate restored the cited source section.",
                "evidence_refs": [_SOURCE_REF],
            }
        ]
    }
    workers = build_reader_repair_subagent_worker_implementations(
        candidate_worker=candidate_worker,
    )
    definition = build_reader_repair_graph_definition()
    identity = _physical_identity(step_id="propose_repair_candidate")

    proposer = workers["propose_repair_candidate"].execute(
        _task(
            definition,
            "propose_repair_candidate",
            {
                "reader_payload": payload.to_dict(),
                "reader_repair_context_pack": context_pack.to_dict(),
            },
        ),
        execution_identity=identity,
    )
    candidate = ReaderRepairPatchCandidate.model_validate(
        proposer.output["reader_repair_patch_candidate"]
    )
    application = apply_reader_repair_candidate(
        payload=payload,
        candidate=candidate,
    )
    observation_identity = _physical_identity(
        step_id="collect_repair_application_observation",
    )
    workers["collect_repair_application_observation"].execute(
        _task(
            definition,
            "collect_repair_application_observation",
            {
                "reader_issue": context_pack.issue.to_dict(),
                "reader_repair_patch_candidate": candidate.to_dict(),
                "reader_repair_application_candidate": application.to_dict(),
            },
        ),
        execution_identity=observation_identity,
    )

    assert candidate_worker.execution_identities == [identity, observation_identity]


def test_reader_repair_subagents_reject_mismatched_execution_identity() -> None:
    payload, context_pack = _payload_and_context()
    candidate_worker = _CandidateWorker()
    candidate_worker.patch_proposal = _patch_proposal(payload)
    worker = build_reader_repair_subagent_worker_implementations(
        candidate_worker=candidate_worker,
    )["propose_repair_candidate"]
    definition = build_reader_repair_graph_definition()
    task = _task(
        definition,
        "propose_repair_candidate",
        {
            "reader_payload": payload.to_dict(),
            "reader_repair_context_pack": context_pack.to_dict(),
        },
    )
    identity = _physical_identity(step_id="propose_repair_candidate")

    for invalid_identity in (
        replace(identity, run_id="other-run"),
        replace(identity, node_id="collect_repair_application_observation"),
        replace(identity, graph_checksum=checksum_for({"graph": "other"})),
    ):
        with pytest.raises(HarnessValidationError) as captured:
            worker.execute(task, execution_identity=invalid_identity)

        assert captured.value.code == (
            "reader_repair_subagent_worker_contract_invalid"
        )
        assert captured.value.details["identity_mismatches"]

    assert candidate_worker.calls == []


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    (
        ("candidate_id", "llm-owned-candidate"),
        ("target_region_refs", [_SOURCE_REF]),
        ("metadata", {"next_step": "publish"}),
    ),
)
def test_reader_repair_proposer_rejects_controller_owned_fields(
    field_name: str,
    field_value: Any,
) -> None:
    payload, context_pack = _payload_and_context()
    candidate_worker = _CandidateWorker()
    candidate_worker.patch_proposal = {
        **_patch_proposal(payload),
        field_name: field_value,
    }
    worker = build_reader_repair_subagent_worker_implementations(
        candidate_worker=candidate_worker,
    )["propose_repair_candidate"]

    with pytest.raises(HarnessValidationError) as captured:
        worker.execute(
            _task(
                build_reader_repair_graph_definition(),
                "propose_repair_candidate",
                {
                    "reader_payload": payload.to_dict(),
                    "reader_repair_context_pack": context_pack.to_dict(),
                },
            )
        )

    assert captured.value.code == (
        "reader_repair_subagent_worker_contract_invalid"
    )
    assert captured.value.details["reserved_fields"] == [field_name]


def test_reader_repair_subagents_reject_task_substitution_and_self_verdicts() -> None:
    payload, context_pack = _payload_and_context()
    candidate_worker = _CandidateWorker()
    candidate_worker.patch_proposal = _patch_proposal(payload)
    workers = build_reader_repair_subagent_worker_implementations(
        candidate_worker=candidate_worker,
    )
    definition = build_reader_repair_graph_definition()
    wrong_type = _task(
        definition,
        "propose_repair_candidate",
        {
            "reader_payload": payload.to_dict(),
            "reader_repair_context_pack": context_pack.to_dict(),
        },
    )
    wrong_type["worker_type"] = HarnessWorkerType.FUNCTION.value

    with pytest.raises(HarnessValidationError) as task_error:
        workers["propose_repair_candidate"].execute(wrong_type)

    assert task_error.value.code == (
        "reader_repair_subagent_worker_contract_invalid"
    )
    assert candidate_worker.calls == []

    proposer = workers["propose_repair_candidate"].execute(
        _task(
            definition,
            "propose_repair_candidate",
            {
                "reader_payload": payload.to_dict(),
                "reader_repair_context_pack": context_pack.to_dict(),
            },
        )
    )
    candidate = ReaderRepairPatchCandidate.model_validate(
        proposer.output["reader_repair_patch_candidate"]
    )
    application = apply_reader_repair_candidate(
        payload=payload,
        candidate=candidate,
    )
    candidate_worker.observation_proposal = {
        "observations": [
            {
                "check_id": "llm-self-verdict",
                "finding": "The model claims this repair passed.",
                "evidence_refs": [_SOURCE_REF],
                "metadata": {"passed": True},
            }
        ]
    }

    with pytest.raises(HarnessValidationError) as verdict_error:
        workers["collect_repair_application_observation"].execute(
            _task(
                definition,
                "collect_repair_application_observation",
                {
                    "reader_issue": context_pack.issue.to_dict(),
                    "reader_repair_patch_candidate": candidate.to_dict(),
                    "reader_repair_application_candidate": application.to_dict(),
                },
            )
        )

    assert verdict_error.value.code == (
        "reader_repair_subagent_worker_contract_invalid"
    )
    assert verdict_error.value.details["model_type"] == (
        "ReaderRepairApplicationObservationCandidate"
    )


def test_reader_repair_subagents_reject_cross_run_context_before_llm_call() -> None:
    payload, context_pack = _payload_and_context()
    other_issue = context_pack.issue.model_copy(update={"run_id": "other-run"})
    other_context = context_pack.model_copy(update={"issue": other_issue})
    candidate_worker = _CandidateWorker()
    candidate_worker.patch_proposal = _patch_proposal(payload)
    worker = build_reader_repair_subagent_worker_implementations(
        candidate_worker=candidate_worker,
    )["propose_repair_candidate"]

    with pytest.raises(HarnessValidationError) as captured:
        worker.execute(
            _task(
                build_reader_repair_graph_definition(),
                "propose_repair_candidate",
                {
                    "reader_payload": payload.to_dict(),
                    "reader_repair_context_pack": other_context.to_dict(),
                },
            )
        )

    assert captured.value.details["issue_run_id"] == "other-run"
    assert candidate_worker.calls == []


def test_reader_repair_subagent_restores_strict_table_row_entries() -> None:
    payload, context_pack = _payload_and_context()
    proposal = _patch_proposal(payload)
    document = proposal["patch_operations"][0]["replacement"]
    document["tables"] = [
        {
            "table_id": "table-1",
            "caption": "Main result",
            "source_ref": _SOURCE_REF,
            "columns": ["metric", "value"],
            "rows": [
                {
                    "entries": [
                        {"key": "metric", "value": "accuracy"},
                        {"key": "value", "value": 0.91},
                    ]
                }
            ],
            "page": 3,
        }
    ]
    candidate_worker = _CandidateWorker()
    candidate_worker.patch_proposal = proposal
    worker = build_reader_repair_subagent_worker_implementations(
        candidate_worker=candidate_worker,
    )["propose_repair_candidate"]

    result = worker.execute(
        _task(
            build_reader_repair_graph_definition(),
            "propose_repair_candidate",
            {
                "reader_payload": payload.to_dict(),
                "reader_repair_context_pack": context_pack.to_dict(),
            },
        )
    )
    candidate = ReaderRepairPatchCandidate.model_validate(
        result.output["reader_repair_patch_candidate"]
    )
    replacement = candidate.patch_operations[0].replacement

    assert replacement.tables[0].rows == [
        {"metric": "accuracy", "value": 0.91}
    ]


def test_reader_repair_subagent_rejects_duplicate_projected_map_keys() -> None:
    payload, context_pack = _payload_and_context()
    proposal = _patch_proposal(payload)
    document = proposal["patch_operations"][0]["replacement"]
    document["tables"] = [
        {
            "table_id": "table-1",
            "caption": "Main result",
            "source_ref": _SOURCE_REF,
            "columns": ["metric"],
            "rows": [
                {
                    "entries": [
                        {"key": "metric", "value": "accuracy"},
                        {"key": "metric", "value": "tampered"},
                    ]
                }
            ],
        }
    ]
    candidate_worker = _CandidateWorker()
    candidate_worker.patch_proposal = proposal
    worker = build_reader_repair_subagent_worker_implementations(
        candidate_worker=candidate_worker,
    )["propose_repair_candidate"]

    with pytest.raises(HarnessValidationError) as captured:
        worker.execute(
            _task(
                build_reader_repair_graph_definition(),
                "propose_repair_candidate",
                {
                    "reader_payload": payload.to_dict(),
                    "reader_repair_context_pack": context_pack.to_dict(),
                },
            )
        )

    assert captured.value.details["duplicate_key"] == "metric"


def test_reader_repair_subagent_restores_strict_evidence_coverage_entries() -> None:
    payload, context_pack = _payload_and_context()
    proposal = _patch_proposal(payload)
    proposal["patch_operations"] = [
        {
            "op": "replace_evidence",
            "source_refs": [_SOURCE_REF],
            "replacement": {
                "pack_id": "reader-repair-evidence-pack",
                "paper_id": payload.paper.paper_id,
                "items": [],
                "coverage": {
                    "entries": [
                        {"key": "method", "value": 0.92},
                        {"key": "experiments", "value": 0.75},
                    ]
                },
                "missing_information": [],
                "lineage": {"source_refs": [_SOURCE_REF]},
            },
        }
    ]
    candidate_worker = _CandidateWorker()
    candidate_worker.patch_proposal = proposal
    worker = build_reader_repair_subagent_worker_implementations(
        candidate_worker=candidate_worker,
    )["propose_repair_candidate"]

    result = worker.execute(
        _task(
            build_reader_repair_graph_definition(),
            "propose_repair_candidate",
            {
                "reader_payload": payload.to_dict(),
                "reader_repair_context_pack": context_pack.to_dict(),
            },
        )
    )
    candidate = ReaderRepairPatchCandidate.model_validate(
        result.output["reader_repair_patch_candidate"]
    )
    replacement = candidate.patch_operations[0].replacement

    assert replacement.coverage == {"method": 0.92, "experiments": 0.75}


def test_reader_repair_subagent_module_stays_out_of_production_composition() -> None:
    root = Path(__file__).resolve().parents[4]
    references: list[str] = []
    for relative in (
        "backend/research/application/single_paper_runtime.py",
        "interfaces/composition/research.py",
    ):
        path = root / relative
        if "reader_repair_subagent_workers" in path.read_text(encoding="utf-8"):
            references.append(relative)

    assert references == []


def _task(
    definition,
    step_id: str,
    inputs: dict[str, Any],
) -> dict[str, Any]:
    activity = definition.activity(step_id)
    assert activity is not None
    return {
        "run_id": _RUN_ID,
        "step_id": step_id,
        "worker_type": activity.worker_type.value,
        "inputs": inputs,
        "metadata": dict(activity.metadata),
    }


def _physical_identity(*, step_id: str) -> GraphExecutionIdentity:
    graph = HarnessGraphCompiler().compile(
        build_reader_repair_graph_definition()
    ).graph
    return GraphExecutionIdentity(
        run_id=_RUN_ID,
        graph_id=graph.graph_id,
        graph_version=graph.graph_version,
        graph_ref=graph.graph_ref.exact_ref,
        graph_checksum=graph.checksum,
        node_id=step_id,
        node_instance_id=f"{step_id}:1",
        activity_id=f"reader-repair-{step_id}:1",
        attempt=1,
    )


def _payload_and_context() -> tuple[ResearchReaderPayload, ReaderRepairContextPack]:
    paper = FakeResearchSourceProvider().paper
    payload = ReaderPayloadBuilder().build(
        paper=paper,
        document=ResearchDocument(
            paper_id=paper.paper_id,
            source_hash="sha256-reader-repair-subagent-workers",
            sections=[],
            lineage=SourceLineage(source_refs=[_SOURCE_REF]),
        ),
    )
    issue = ReaderRepairIssueDetector().detect(
        payload,
        run_id=_RUN_ID,
        source_format="pdf",
        created_at=_NOW,
    )[0]
    context = ReaderRepairContextPack(
        context_id="reader-repair-subagent-context",
        issue=issue,
        repair_constraints=["preserve source lineage"],
        source_refs=[_SOURCE_REF],
        source_lineage=SourceLineage(source_refs=[_SOURCE_REF]),
    )
    return payload, context


def _patch_proposal(payload: ResearchReaderPayload) -> dict[str, Any]:
    section = ResearchSection(
        section_id="section-1",
        title="Introduction",
        text="Source-backed introduction.",
        source_ref=_SOURCE_REF,
    )
    document = ResearchDocument(
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
    return {
        "repair_summary": "Restore the source-backed section and navigation.",
        "patch_operations": [
            {
                "op": "replace_document",
                "source_refs": [_SOURCE_REF],
                "replacement": document.to_dict(),
            },
            {
                "op": "replace_navigation",
                "source_refs": [_SOURCE_REF],
                "replacement": [navigation.to_dict()],
            },
        ],
        "expected_effect": "Reader navigation matches the repaired document.",
        "risks": [],
        "confidence": 0.9,
    }
