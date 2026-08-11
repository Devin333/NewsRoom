from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from framework.llm import (
    LLMStructuredOutputProjectionError,
    LOCAL_STRUCTURED_OUTPUT_DIALECT,
    ProviderStructuredOutputCapability,
    ProviderStructuredOutputPolicy,
    ProviderStructuredOutputRelease,
    ProviderStructuredOutputRollback,
    StructuredOutputEvaluationError,
    build_provider_structured_output_release,
    compile_structured_output_contract,
    load_structured_output_evaluation_suite,
    project_structured_output_contract,
    structured_output_content_digest,
    structured_output_enforcement_keywords,
)
from scripts.structured_output_eval import main as structured_output_eval_main


_ROOT = Path(__file__).resolve().parents[3]
_CORPUS = (
    _ROOT
    / "configs"
    / "llm"
    / "structured_output"
    / "corpora"
    / "provider-schema-corpus-v1.json"
)
_OBSERVATIONS = (
    _ROOT
    / "configs"
    / "llm"
    / "structured_output"
    / "evaluations"
    / "recorded-reference-native-v1.json"
)
_APPROVED_RELEASE = (
    _ROOT
    / "configs"
    / "llm"
    / "structured_output"
    / "releases"
    / "recorded-reference-native-v1.json"
)
_HELD_RELEASE = (
    _ROOT
    / "configs"
    / "llm"
    / "structured_output"
    / "releases"
    / "dashscope-deepseek-v4-flash-held-v1.json"
)
_SIMPLE_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


def test_recorded_provider_evaluation_passes_every_independent_gate() -> None:
    report = load_structured_output_evaluation_suite(
        _CORPUS,
        _OBSERVATIONS,
    ).evaluate()

    assert report.promotion_eligible is True
    assert report.expectation_gate_passed is True
    assert all(gate.passed for gate in report.metric_gates)
    assert report.metrics == {
        "schema_validity_rate": 1.0,
        "first_pass_validity_rate": 0.9,
        "repair_success_rate": 1.0,
        "answer_quality": 0.905,
        "evidence_grounding": 0.935,
        "citation_completeness": pytest.approx(0.9625),
        "provider_rejection_rate": 0.0,
        "latency_p95_ms": 1490.0,
        "average_total_tokens": 474.1,
        "average_cost_usd": pytest.approx(0.00132),
    }
    assert (
        report.report_digest
        == "sha256:a6ff539b00dc63660f35bb0776c2a4b7aa9586c2c148cd8b2447262c05b01a08"
    )


def test_quality_regression_cannot_be_compensated_by_perfect_schema_metrics(
    tmp_path: Path,
) -> None:
    payload = json.loads(_OBSERVATIONS.read_text(encoding="utf-8"))
    for observation in payload["observations"]:
        if observation["split"] == "held_out_research":
            observation["answer_quality"] = 0.5
    payload["content_digest"] = structured_output_content_digest(payload)
    observations_path = tmp_path / "quality-regression.json"
    observations_path.write_text(json.dumps(payload), encoding="utf-8")

    report = load_structured_output_evaluation_suite(
        _CORPUS,
        observations_path,
    ).evaluate()

    gates = {gate.metric: gate for gate in report.metric_gates}
    assert report.metrics["schema_validity_rate"] == 1.0
    assert gates["schema_validity_rate"].passed is True
    assert gates["answer_quality"].passed is False
    assert report.promotion_eligible is False
    with pytest.raises(
        StructuredOutputEvaluationError,
        match="failed evaluation report",
    ):
        _build_release(report)


def test_observation_tamper_fails_before_evaluation(tmp_path: Path) -> None:
    payload = json.loads(_OBSERVATIONS.read_text(encoding="utf-8"))
    payload["observations"][0]["attempts"][0]["response_text"] = "{}"
    observations_path = tmp_path / "tampered.json"
    observations_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        StructuredOutputEvaluationError,
        match="content_digest does not match",
    ):
        load_structured_output_evaluation_suite(_CORPUS, observations_path)


def test_evaluation_requires_every_schema_corpus_case(tmp_path: Path) -> None:
    payload = json.loads(_OBSERVATIONS.read_text(encoding="utf-8"))
    payload["observations"] = [
        observation
        for observation in payload["observations"]
        if observation["schema_case_id"] != "numeric-array-semantics-v1"
    ]
    payload["content_digest"] = structured_output_content_digest(payload)
    observations_path = tmp_path / "incomplete-corpus.json"
    observations_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        StructuredOutputEvaluationError,
        match="does not cover schema corpus cases: numeric-array-semantics-v1",
    ):
        load_structured_output_evaluation_suite(_CORPUS, observations_path)


def test_approved_release_is_reproducible_from_evaluation_report() -> None:
    report = load_structured_output_evaluation_suite(
        _CORPUS,
        _OBSERVATIONS,
    ).evaluate()
    built = _build_release(report)
    stored = ProviderStructuredOutputRelease.from_dict(
        json.loads(_APPROVED_RELEASE.read_text(encoding="utf-8"))
    )

    assert built == stored
    assert built.digest == stored.record_digest
    assert built.is_enabled is True
    assert built.rollback.action == "json_object_local_gate"


def test_evaluation_cli_replays_and_verifies_release(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "evaluation-report.json"

    exit_code = structured_output_eval_main(
        [
            "--schema-corpus",
            str(_CORPUS),
            "--observations",
            str(_OBSERVATIONS),
            "--release-record",
            str(_APPROVED_RELEASE),
            "--output",
            str(output_path),
        ]
    )

    stdout_payload = json.loads(capsys.readouterr().out)
    stored_payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert stdout_payload == stored_payload
    assert stored_payload["promotion_eligible"] is True
    assert stored_payload["release_verification"] == {
        "issues": [],
        "passed": True,
        "record_digest": (
            "sha256:7d3f0f0b7ef58f187f0df1905b6eca30278e4c30bb13ecf9cc2b684b7ce2bc5c"
        ),
        "release_id": "recorded-reference-native-v1",
    }


def test_shadow_release_never_selects_native_provider_enforcement() -> None:
    approved = ProviderStructuredOutputRelease.from_dict(
        json.loads(_APPROVED_RELEASE.read_text(encoding="utf-8"))
    )
    shadow = replace(
        approved,
        rollout_state="shadow",
        rollout_revision="recorded-reference-shadow-v1",
        record_digest=None,
    )
    capability = _native_capability(shadow, supports_json_fallback=True)
    contract = compile_structured_output_contract(_SIMPLE_SCHEMA)

    projection = project_structured_output_contract(
        contract,
        capability,
        policy=ProviderStructuredOutputPolicy(
            allow_json_object_local_gate=True,
            workflow_scope="research.candidate",
        ),
    )

    assert projection.mode == "json_object_local_gate"
    assert projection.provider_rollout_state == "shadow"
    assert projection.shadow_candidate_mode == "native_strict"
    assert projection.provider_schema is None


@pytest.mark.parametrize(
    ("release", "scope", "reason"),
    [
        (None, "research.candidate", "provider_release_missing"),
        ("approved", "daily.writer", "provider_release_scope_ineligible"),
    ],
)
def test_native_release_ineligibility_fails_closed_before_transport(
    release: str | None,
    scope: str,
    reason: str,
) -> None:
    approved = ProviderStructuredOutputRelease.from_dict(
        json.loads(_APPROVED_RELEASE.read_text(encoding="utf-8"))
    )
    capability = _native_capability(approved if release else None)
    contract = compile_structured_output_contract(_SIMPLE_SCHEMA)

    with pytest.raises(LLMStructuredOutputProjectionError) as raised:
        project_structured_output_contract(
            contract,
            capability,
            policy=ProviderStructuredOutputPolicy(
                require_native_enforcement=True,
                workflow_scope=scope,
            ),
        )

    assert raised.value.code == "provider_release_ineligible"
    assert reason in {
        diagnostic.validator for diagnostic in raised.value.diagnostics
    }


def test_real_provider_release_remains_explicitly_held() -> None:
    release = ProviderStructuredOutputRelease.from_dict(
        json.loads(_HELD_RELEASE.read_text(encoding="utf-8"))
    )

    assert release.provider == "dashscope"
    assert release.status == "held"
    assert release.rollout_state == "disabled"
    assert release.evaluation_passed is False
    assert release.is_enabled is False
    assert release.rollback.action == "reject"


def _native_capability(
    release: ProviderStructuredOutputRelease | None,
    *,
    supports_json_fallback: bool = False,
) -> ProviderStructuredOutputCapability:
    contract = compile_structured_output_contract(_SIMPLE_SCHEMA)
    return ProviderStructuredOutputCapability(
        provider="recorded",
        deployment="recorded-research-model",
        mode="native_strict",
        supported_dialect=LOCAL_STRUCTURED_OUTPUT_DIALECT,
        supported_keywords=structured_output_enforcement_keywords(
            contract.canonical_schema
        ),
        supports_local_refs=True,
        supports_json_object_fallback=supports_json_fallback,
        supports_stream_terminal_validation=True,
        revision="recorded-research-native-v1",
        release=release,
    )


def _build_release(report):  # type: ignore[no-untyped-def]
    return build_provider_structured_output_release(
        report,
        release_id="recorded-reference-native-v1",
        workflow_scopes=("research.candidate", "structured-output-evaluation"),
        rollout_revision="recorded-reference-rollout-v1",
        rollback=ProviderStructuredOutputRollback(
            action="json_object_local_gate",
            triggers=(
                "schema_validity_regression",
                "research_quality_regression",
                "latency_or_cost_regression",
                "operator_request",
            ),
        ),
        approved_by="structured-output-release-gate-v1",
        approved_at="2026-08-11T00:00:00Z",
        owner="llm-platform",
        reason=(
            "Deterministic recorded-transport reference release; not evidence "
            "for any external provider."
        ),
    )
