from __future__ import annotations

import pytest

from framework.events.canonical import checksum_for
from framework.harness import (
    FORBIDDEN_WORKER_RESULT_KEYS,
    HarnessWorkerEvidence,
    HarnessValidationError,
    HarnessSideEffectIntent,
    HarnessWorkerResult,
    harness_worker_candidate_ref,
)


@pytest.mark.parametrize(
    "forbidden_key",
    sorted(FORBIDDEN_WORKER_RESULT_KEYS),
)
def test_worker_result_rejects_flow_control_fields(forbidden_key: str) -> None:
    with pytest.raises(HarnessValidationError) as captured:
        HarnessWorkerResult(status="succeeded", output={forbidden_key: True})

    assert captured.value.details["forbidden"] == [forbidden_key]


def test_worker_result_exposes_candidate_data_only() -> None:
    result = HarnessWorkerResult(
        status="succeeded",
        output={"candidate_summary": "A grounded candidate."},
        artifacts=("artifact://candidate",),
        diagnostics={"warnings": []},
        metrics={"tokens": 12},
    )

    assert result.to_dict() == {
        "status": "succeeded",
        "output": {"candidate_summary": "A grounded candidate."},
        "artifacts": ["artifact://candidate"],
        "diagnostics": {"warnings": []},
        "metrics": {"tokens": 12},
        "error": None,
    }


def test_worker_result_adds_typed_evidence_only_when_present() -> None:
    evidence = HarnessWorkerEvidence(
        evidence_type="subagent_attempt",
        payload={"transcript_ref": "subagent-transcript://v1/run/transcript"},
    )
    result = HarnessWorkerResult(status="succeeded", evidence=(evidence,))

    assert result.to_dict()["evidence"] == [evidence.to_dict()]
    assert harness_worker_candidate_ref(result.to_dict()) == result.candidate_result_ref


def test_candidate_ref_preserves_legacy_payload_shape_without_evidence() -> None:
    legacy = {
        "status": "succeeded",
        "output": {"candidate": "legacy"},
        "artifacts": [],
        "diagnostics": {},
        "metrics": {},
        "error": None,
    }

    assert harness_worker_candidate_ref(legacy) == checksum_for(legacy)


def test_worker_result_allows_observations_and_completed_domain_facts() -> None:
    result = HarnessWorkerResult(
        status="succeeded",
        output={
            "quality_observation": {"score": 0.9},
            "authorization_observation": {"requested_tools": ["search"]},
            "memory_write_candidate": {"namespace": "research.private"},
            "publication_observation": {"published": True},
        },
    )

    assert result.output["quality_observation"] == {"score": 0.9}


@pytest.mark.parametrize(
    "channel",
    ("output", "diagnostics", "metrics"),
)
def test_worker_result_rejects_nested_decision_aliases_in_all_untyped_channels(channel: str) -> None:
    with pytest.raises(HarnessValidationError) as captured:
        HarnessWorkerResult(
            status="succeeded",
            **{channel: {"nested": {"published": True}}},
        )

    assert captured.value.code == "worker_decision_field_rejected"
    assert captured.value.details["forbidden_paths"] == [f"{channel}.nested.published"]


def test_worker_result_artifact_refs_are_strict_candidate_strings() -> None:
    with pytest.raises(HarnessValidationError, match="artifact refs"):
        HarnessWorkerResult(status="succeeded", artifacts=(object(),))  # type: ignore[arg-type]

    result = HarnessWorkerResult(status="succeeded", artifacts=("candidate://run/a",))
    assert result.artifacts == ("candidate://run/a",)


def test_typed_intent_payload_is_opaque_candidate_data() -> None:
    intent = HarnessSideEffectIntent(
        effect_id="effect-1",
        kind="artifact",
        run_id="run-1",
        origin="worker",
        atomic_group="group-1",
        identity_scope_ref=checksum_for({"tenant_id": "tenant-1"}),
        subject_scope_ref=checksum_for({"paper_id": "paper-1"}),
        step_id="publish",
        worker_result_ref=checksum_for({"worker": 1}),
        candidate_checksum=checksum_for({"candidate": 1}),
        handler="research.artifact@1",
        payload={"published": "domain fact allowed by typed intent schema"},
    )

    result = HarnessWorkerResult(status="succeeded", effect_intent=intent)

    assert result.effect_intent == intent
    assert result.to_dict()["effect_intent"]["payload"]["published"].startswith("domain fact")


def test_worker_result_rejects_multiple_intents_instead_of_coercing_a_list() -> None:
    with pytest.raises(HarnessValidationError, match="typed HarnessSideEffectIntent"):
        HarnessWorkerResult(status="succeeded", effect_intent=[])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field_name",
    (
        "artifact_class",
        "cache_eligible",
        "materialization_mode",
        "persistence",
        "persistence_decision",
        "persistence_mode",
        "quota_override",
        "required_for_publication",
        "required_for_replay",
        "result_persistence",
        "result_retention",
        "retention",
        "retention_class",
        "storage_tier",
    ),
)
def test_worker_result_rejects_persistence_authority_fields(
    field_name: str,
) -> None:
    with pytest.raises(HarnessValidationError) as captured:
        HarnessWorkerResult(
            status="succeeded",
            diagnostics={"nested": {field_name: "worker-choice"}},
        )

    assert captured.value.code == "worker_decision_field_rejected"
    assert captured.value.details["forbidden_paths"] == [
        f"diagnostics.nested.{field_name}"
    ]
