from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from framework.events.canonical import checksum_for
from framework.harness import HarnessValidationError, HarnessWorkerStatus
from framework.harness.graph import HarnessWorkerType

from business.research.domain import (
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
from business.research.graphs.reader_repair import (
    READER_REPAIR_SUBAGENT_IDS,
    build_reader_repair_graph_definition,
)
from business.research.graphs.reader_repair_subagent_workers import (
    READER_REPAIR_APPLICATION_OBSERVATION_TASK,
    READER_REPAIR_PATCH_CANDIDATE_TASK,
    build_reader_repair_subagent_worker_implementations,
)
from business.research.reader import ReaderPayloadBuilder
from business.research.reader_repair import (
    ReaderRepairIssueDetector,
    apply_reader_repair_candidate,
    reader_repair_component_checksum,
)
from tests.business.research.fakes import FakeResearchSourceProvider


_RUN_ID = "reader-repair-subagent-run"
_SOURCE_REF = "paper://paper-harness-001/raw"
_NOW = datetime(2026, 8, 16, 10, 0, tzinfo=UTC)


class _CandidateWorker:
    def __init__(self) -> None:
        self.patch_proposal: dict[str, Any] | None = None
        self.observation_proposal: dict[str, Any] | None = None
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def generate_candidate(
        self,
        *,
        task: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append((task, deepcopy(payload)))
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


def test_reader_repair_subagent_module_stays_out_of_production_composition() -> None:
    root = Path(__file__).resolve().parents[4]
    references: list[str] = []
    for relative in (
        "business/research/application/single_paper_runtime.py",
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
