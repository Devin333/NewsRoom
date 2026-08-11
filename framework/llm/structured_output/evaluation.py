from __future__ import annotations

import json
import math
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from framework.llm.structured_output.contracts import LLMStructuredOutputError
from framework.llm.structured_output.decoder import decode_structured_output
from framework.llm.structured_output.preflight import (
    compile_structured_output_contract,
)
from framework.llm.structured_output.validator import (
    validate_compiled_structured_output,
)
from framework.llm.structured_output.release import (
    ProviderStructuredOutputRelease,
    ProviderStructuredOutputRollback,
)


EvaluationMetricDirection = Literal["min", "max"]

HIGHER_IS_BETTER_METRICS = (
    "schema_validity_rate",
    "first_pass_validity_rate",
    "repair_success_rate",
    "answer_quality",
    "evidence_grounding",
    "citation_completeness",
)
LOWER_IS_BETTER_METRICS = (
    "provider_rejection_rate",
    "latency_p95_ms",
    "average_total_tokens",
    "average_cost_usd",
)
REQUIRED_EVALUATION_METRICS = (
    *HIGHER_IS_BETTER_METRICS,
    *LOWER_IS_BETTER_METRICS,
)

_CORPUS_SCHEMA_VERSION = "provider-schema-corpus.v1"
_OBSERVATION_SCHEMA_VERSION = "provider-observations.v1"
_SPLITS = frozenset({"capability", "held_out_research"})


class StructuredOutputEvaluationError(ValueError):
    """Raised when evaluation evidence is malformed or fails integrity checks."""


@dataclass(frozen=True)
class StructuredOutputSchemaCase:
    case_id: str
    category: str
    schema: dict[str, Any]

    def __post_init__(self) -> None:
        if not _optional_text(self.case_id):
            raise StructuredOutputEvaluationError("schema case_id is required")
        if not _optional_text(self.category):
            raise StructuredOutputEvaluationError("schema category is required")
        if not isinstance(self.schema, dict):
            raise StructuredOutputEvaluationError("schema case schema must be an object")


@dataclass(frozen=True)
class StructuredOutputSchemaCorpus:
    corpus_id: str
    revision: str
    cases: tuple[StructuredOutputSchemaCase, ...]
    upstream_sources: tuple[dict[str, Any], ...]
    license_disposition: str
    content_digest: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> StructuredOutputSchemaCorpus:
        _require_schema_version(payload, _CORPUS_SCHEMA_VERSION)
        _verify_content_digest(payload)
        raw_cases = payload.get("cases")
        if not isinstance(raw_cases, list) or not raw_cases:
            raise StructuredOutputEvaluationError("schema corpus cases must be a non-empty list")
        cases: list[StructuredOutputSchemaCase] = []
        seen_ids: set[str] = set()
        for raw_case in raw_cases:
            if not isinstance(raw_case, Mapping):
                raise StructuredOutputEvaluationError("schema corpus case must be an object")
            case = StructuredOutputSchemaCase(
                case_id=_required_text(raw_case.get("case_id"), "case_id"),
                category=_required_text(raw_case.get("category"), "category"),
                schema=_required_object(raw_case.get("schema"), "schema"),
            )
            if case.case_id in seen_ids:
                raise StructuredOutputEvaluationError(
                    f"schema corpus case_id is duplicated: {case.case_id}"
                )
            seen_ids.add(case.case_id)
            cases.append(case)
        sources = _object_tuple(payload.get("upstream_sources"), "upstream_sources")
        if not sources:
            raise StructuredOutputEvaluationError("upstream_sources must not be empty")
        for source in sources:
            if not _optional_text(source.get("repository")) or not _optional_text(
                source.get("commit")
            ):
                raise StructuredOutputEvaluationError(
                    "every upstream source requires repository and pinned commit"
                )
        disposition = _required_text(
            payload.get("license_disposition"), "license_disposition"
        )
        return cls(
            corpus_id=_required_text(payload.get("corpus_id"), "corpus_id"),
            revision=_required_text(payload.get("revision"), "revision"),
            cases=tuple(cases),
            upstream_sources=sources,
            license_disposition=disposition,
            content_digest=_required_digest(payload.get("content_digest"), "content_digest"),
        )

    @property
    def by_id(self) -> dict[str, StructuredOutputSchemaCase]:
        return {case.case_id: case for case in self.cases}


@dataclass(frozen=True)
class StructuredOutputObservedAttempt:
    response_text: str
    latency_ms: float
    input_tokens: int
    output_tokens: int
    cost_usd: float

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> StructuredOutputObservedAttempt:
        response_text = payload.get("response_text")
        if not isinstance(response_text, str):
            raise StructuredOutputEvaluationError("attempt response_text must be text")
        return cls(
            response_text=response_text,
            latency_ms=_non_negative_number(payload.get("latency_ms"), "latency_ms"),
            input_tokens=_non_negative_int(payload.get("input_tokens"), "input_tokens"),
            output_tokens=_non_negative_int(payload.get("output_tokens"), "output_tokens"),
            cost_usd=_non_negative_number(payload.get("cost_usd"), "cost_usd"),
        )


@dataclass(frozen=True)
class StructuredOutputObservation:
    case_id: str
    schema_case_id: str
    split: str
    provider_schema_rejected: bool
    attempts: tuple[StructuredOutputObservedAttempt, ...]
    expected_final_valid: bool
    answer_quality: float | None = None
    evidence_grounding: float | None = None
    citation_completeness: float | None = None
    evaluator_refs: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> StructuredOutputObservation:
        split = _required_text(payload.get("split"), "split")
        if split not in _SPLITS:
            raise StructuredOutputEvaluationError(f"unsupported observation split: {split}")
        rejected = _strict_bool(
            payload.get("provider_schema_rejected", False),
            "provider_schema_rejected",
        )
        raw_attempts = payload.get("attempts")
        if not isinstance(raw_attempts, list):
            raise StructuredOutputEvaluationError("observation attempts must be a list")
        attempts = tuple(
            StructuredOutputObservedAttempt.from_dict(item)
            for item in raw_attempts
            if isinstance(item, Mapping)
        )
        if len(attempts) != len(raw_attempts):
            raise StructuredOutputEvaluationError("observation attempt must be an object")
        if rejected == bool(attempts):
            raise StructuredOutputEvaluationError(
                "provider rejection must have no attempts; accepted case must have attempts"
            )
        quality_values: dict[str, float | None] = {}
        for field_name in (
            "answer_quality",
            "evidence_grounding",
            "citation_completeness",
        ):
            value = payload.get(field_name)
            quality_values[field_name] = (
                None if value is None else _unit_interval(value, field_name)
            )
        refs = _text_tuple(payload.get("evaluator_refs", ()), "evaluator_refs")
        if split == "held_out_research" and (
            any(value is None for value in quality_values.values()) or not refs
        ):
            raise StructuredOutputEvaluationError(
                "held-out Research observation requires quality scores and evaluator_refs"
            )
        return cls(
            case_id=_required_text(payload.get("case_id"), "case_id"),
            schema_case_id=_required_text(
                payload.get("schema_case_id"), "schema_case_id"
            ),
            split=split,
            provider_schema_rejected=rejected,
            attempts=attempts,
            expected_final_valid=_strict_bool(
                payload.get("expected_final_valid"), "expected_final_valid"
            ),
            answer_quality=quality_values["answer_quality"],
            evidence_grounding=quality_values["evidence_grounding"],
            citation_completeness=quality_values["citation_completeness"],
            evaluator_refs=refs,
        )


@dataclass(frozen=True)
class StructuredOutputObservationSet:
    observation_set_id: str
    revision: str
    schema_corpus_revision: str
    schema_corpus_digest: str
    provider: str
    deployment: str
    capability_revision: str
    projection_mode: str
    evidence_kind: str
    baseline_revision: str
    baselines: dict[str, float]
    thresholds: dict[str, float]
    regression_tolerances: dict[str, float]
    observations: tuple[StructuredOutputObservation, ...]
    evidence_refs: tuple[str, ...]
    content_digest: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> StructuredOutputObservationSet:
        _require_schema_version(payload, _OBSERVATION_SCHEMA_VERSION)
        _verify_content_digest(payload)
        baselines = _metric_mapping(payload.get("baselines"), "baselines")
        thresholds = _metric_mapping(payload.get("thresholds"), "thresholds")
        tolerances = _metric_mapping(
            payload.get("regression_tolerances"), "regression_tolerances"
        )
        for mapping_name, values in (
            ("baselines", baselines),
            ("thresholds", thresholds),
            ("regression_tolerances", tolerances),
        ):
            missing = sorted(set(REQUIRED_EVALUATION_METRICS) - set(values))
            unknown = sorted(set(values) - set(REQUIRED_EVALUATION_METRICS))
            if missing or unknown:
                raise StructuredOutputEvaluationError(
                    f"{mapping_name} metric set mismatch; missing={missing}, unknown={unknown}"
                )
        raw_observations = payload.get("observations")
        if not isinstance(raw_observations, list) or not raw_observations:
            raise StructuredOutputEvaluationError(
                "observations must be a non-empty list"
            )
        observations = tuple(
            StructuredOutputObservation.from_dict(item)
            for item in raw_observations
            if isinstance(item, Mapping)
        )
        if len(observations) != len(raw_observations):
            raise StructuredOutputEvaluationError("observation must be an object")
        case_ids = [item.case_id for item in observations]
        if len(set(case_ids)) != len(case_ids):
            raise StructuredOutputEvaluationError("observation case_id must be unique")
        if not any(item.split == "capability" for item in observations):
            raise StructuredOutputEvaluationError("capability observations are required")
        if not any(item.split == "held_out_research" for item in observations):
            raise StructuredOutputEvaluationError(
                "held-out Research observations are required"
            )
        return cls(
            observation_set_id=_required_text(
                payload.get("observation_set_id"), "observation_set_id"
            ),
            revision=_required_text(payload.get("revision"), "revision"),
            schema_corpus_revision=_required_text(
                payload.get("schema_corpus_revision"), "schema_corpus_revision"
            ),
            schema_corpus_digest=_required_digest(
                payload.get("schema_corpus_digest"), "schema_corpus_digest"
            ),
            provider=_required_text(payload.get("provider"), "provider"),
            deployment=_required_text(payload.get("deployment"), "deployment"),
            capability_revision=_required_text(
                payload.get("capability_revision"), "capability_revision"
            ),
            projection_mode=_required_text(
                payload.get("projection_mode"), "projection_mode"
            ),
            evidence_kind=_required_text(payload.get("evidence_kind"), "evidence_kind"),
            baseline_revision=_required_text(
                payload.get("baseline_revision"), "baseline_revision"
            ),
            baselines=baselines,
            thresholds=thresholds,
            regression_tolerances=tolerances,
            observations=observations,
            evidence_refs=_required_text_tuple(
                payload.get("evidence_refs"), "evidence_refs"
            ),
            content_digest=_required_digest(
                payload.get("content_digest"), "content_digest"
            ),
        )

    @property
    def baseline_digest(self) -> str:
        return structured_output_content_digest(
            {
                "baseline_revision": self.baseline_revision,
                "baselines": self.baselines,
                "thresholds": self.thresholds,
                "regression_tolerances": self.regression_tolerances,
            }
        )


@dataclass(frozen=True)
class StructuredOutputEvaluationCaseResult:
    case_id: str
    split: str
    schema_case_id: str
    schema_digest: str
    first_pass_valid: bool
    final_valid: bool
    repaired: bool
    provider_schema_rejected: bool
    expectation_matched: bool
    diagnostic_codes: tuple[str, ...]
    latency_ms: float
    total_tokens: int
    cost_usd: float
    answer_quality: float | None
    evidence_grounding: float | None
    citation_completeness: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "split": self.split,
            "schema_case_id": self.schema_case_id,
            "schema_digest": self.schema_digest,
            "first_pass_valid": self.first_pass_valid,
            "final_valid": self.final_valid,
            "repaired": self.repaired,
            "provider_schema_rejected": self.provider_schema_rejected,
            "expectation_matched": self.expectation_matched,
            "diagnostic_codes": list(self.diagnostic_codes),
            "latency_ms": self.latency_ms,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "answer_quality": self.answer_quality,
            "evidence_grounding": self.evidence_grounding,
            "citation_completeness": self.citation_completeness,
        }


@dataclass(frozen=True)
class StructuredOutputMetricGate:
    metric: str
    direction: EvaluationMetricDirection
    actual: float
    threshold: float
    baseline: float
    regression_tolerance: float
    passed: bool
    threshold_passed: bool
    regression_passed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "direction": self.direction,
            "actual": self.actual,
            "threshold": self.threshold,
            "baseline": self.baseline,
            "regression_tolerance": self.regression_tolerance,
            "passed": self.passed,
            "threshold_passed": self.threshold_passed,
            "regression_passed": self.regression_passed,
        }


@dataclass(frozen=True)
class StructuredOutputEvaluationReport:
    provider: str
    deployment: str
    capability_revision: str
    projection_mode: str
    corpus_revision: str
    corpus_digest: str
    observation_revision: str
    observation_digest: str
    baseline_revision: str
    baseline_digest: str
    evidence_kind: str
    evidence_refs: tuple[str, ...]
    metrics: dict[str, float]
    metric_gates: tuple[StructuredOutputMetricGate, ...]
    case_results: tuple[StructuredOutputEvaluationCaseResult, ...]
    expectation_gate_passed: bool
    promotion_eligible: bool

    @property
    def report_digest(self) -> str:
        return structured_output_content_digest(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": "provider-evaluation-report.v1",
            "provider": self.provider,
            "deployment": self.deployment,
            "capability_revision": self.capability_revision,
            "projection_mode": self.projection_mode,
            "corpus_revision": self.corpus_revision,
            "corpus_digest": self.corpus_digest,
            "observation_revision": self.observation_revision,
            "observation_digest": self.observation_digest,
            "baseline_revision": self.baseline_revision,
            "baseline_digest": self.baseline_digest,
            "evidence_kind": self.evidence_kind,
            "evidence_refs": list(self.evidence_refs),
            "metrics": dict(self.metrics),
            "metric_gates": [gate.to_dict() for gate in self.metric_gates],
            "case_results": [result.to_dict() for result in self.case_results],
            "expectation_gate_passed": self.expectation_gate_passed,
            "promotion_eligible": self.promotion_eligible,
        }
        if include_digest:
            payload["report_digest"] = self.report_digest
        return payload


@dataclass(frozen=True)
class StructuredOutputEvaluationSuite:
    corpus: StructuredOutputSchemaCorpus
    observations: StructuredOutputObservationSet

    def __post_init__(self) -> None:
        if self.observations.schema_corpus_revision != self.corpus.revision:
            raise StructuredOutputEvaluationError(
                "observation schema_corpus_revision does not match corpus"
            )
        if self.observations.schema_corpus_digest != self.corpus.content_digest:
            raise StructuredOutputEvaluationError(
                "observation schema_corpus_digest does not match corpus"
            )
        missing = sorted(
            {item.schema_case_id for item in self.observations.observations}
            - set(self.corpus.by_id)
        )
        if missing:
            raise StructuredOutputEvaluationError(
                "observation references unknown schema cases: " + ", ".join(missing)
            )
        unobserved = sorted(
            set(self.corpus.by_id)
            - {item.schema_case_id for item in self.observations.observations}
        )
        if unobserved:
            raise StructuredOutputEvaluationError(
                "evaluation does not cover schema corpus cases: "
                + ", ".join(unobserved)
            )

    def evaluate(self) -> StructuredOutputEvaluationReport:
        case_results = tuple(
            self._evaluate_case(observation)
            for observation in self.observations.observations
        )
        metrics = _aggregate_metrics(case_results)
        gates = tuple(
            _metric_gate(
                metric,
                actual=metrics[metric],
                threshold=self.observations.thresholds[metric],
                baseline=self.observations.baselines[metric],
                tolerance=self.observations.regression_tolerances[metric],
            )
            for metric in REQUIRED_EVALUATION_METRICS
        )
        expectations_passed = all(result.expectation_matched for result in case_results)
        promotion_eligible = expectations_passed and all(gate.passed for gate in gates)
        return StructuredOutputEvaluationReport(
            provider=self.observations.provider,
            deployment=self.observations.deployment,
            capability_revision=self.observations.capability_revision,
            projection_mode=self.observations.projection_mode,
            corpus_revision=self.corpus.revision,
            corpus_digest=self.corpus.content_digest,
            observation_revision=self.observations.revision,
            observation_digest=self.observations.content_digest,
            baseline_revision=self.observations.baseline_revision,
            baseline_digest=self.observations.baseline_digest,
            evidence_kind=self.observations.evidence_kind,
            evidence_refs=self.observations.evidence_refs,
            metrics=metrics,
            metric_gates=gates,
            case_results=case_results,
            expectation_gate_passed=expectations_passed,
            promotion_eligible=promotion_eligible,
        )

    def _evaluate_case(
        self,
        observation: StructuredOutputObservation,
    ) -> StructuredOutputEvaluationCaseResult:
        schema_case = self.corpus.by_id[observation.schema_case_id]
        contract = compile_structured_output_contract(
            schema_case.schema,
            schema_name=schema_case.case_id,
        )
        validity: list[bool] = []
        diagnostic_codes: list[str] = []
        for attempt in observation.attempts:
            try:
                decoded = decode_structured_output(attempt.response_text)
                validate_compiled_structured_output(decoded, contract)
            except LLMStructuredOutputError as exc:
                validity.append(False)
                diagnostic_codes.extend(
                    diagnostic.code for diagnostic in exc.diagnostics
                )
            else:
                validity.append(True)
        first_pass_valid = bool(validity and validity[0])
        final_valid = bool(validity and validity[-1])
        return StructuredOutputEvaluationCaseResult(
            case_id=observation.case_id,
            split=observation.split,
            schema_case_id=observation.schema_case_id,
            schema_digest=contract.schema_digest,
            first_pass_valid=first_pass_valid,
            final_valid=final_valid,
            repaired=(len(validity) > 1 and not validity[0] and validity[-1]),
            provider_schema_rejected=observation.provider_schema_rejected,
            expectation_matched=(
                final_valid == observation.expected_final_valid
                and not observation.provider_schema_rejected
            ),
            diagnostic_codes=tuple(diagnostic_codes),
            latency_ms=sum(attempt.latency_ms for attempt in observation.attempts),
            total_tokens=sum(
                attempt.input_tokens + attempt.output_tokens
                for attempt in observation.attempts
            ),
            cost_usd=sum(attempt.cost_usd for attempt in observation.attempts),
            answer_quality=observation.answer_quality,
            evidence_grounding=observation.evidence_grounding,
            citation_completeness=observation.citation_completeness,
        )


def load_structured_output_evaluation_suite(
    schema_corpus_path: str | Path,
    observation_path: str | Path,
) -> StructuredOutputEvaluationSuite:
    corpus_payload = _load_json_object(schema_corpus_path)
    observation_payload = _load_json_object(observation_path)
    return StructuredOutputEvaluationSuite(
        corpus=StructuredOutputSchemaCorpus.from_dict(corpus_payload),
        observations=StructuredOutputObservationSet.from_dict(observation_payload),
    )


def build_provider_structured_output_release(
    report: StructuredOutputEvaluationReport,
    *,
    release_id: str,
    workflow_scopes: Sequence[str],
    rollout_revision: str,
    rollback: ProviderStructuredOutputRollback,
    approved_by: str,
    approved_at: str,
    owner: str = "llm-platform",
    rollout_state: Literal["shadow", "enabled"] = "enabled",
    reason: str | None = None,
) -> ProviderStructuredOutputRelease:
    if not report.promotion_eligible:
        raise StructuredOutputEvaluationError(
            "failed evaluation report cannot produce an approved provider release"
        )
    return ProviderStructuredOutputRelease(
        release_id=release_id,
        provider=report.provider,
        deployment=report.deployment,
        capability_revision=report.capability_revision,
        approved_modes=frozenset({report.projection_mode}),
        status="approved",
        rollout_state=rollout_state,
        workflow_scopes=tuple(workflow_scopes),
        corpus_revision=report.corpus_revision,
        corpus_digest=report.corpus_digest,
        observation_revision=report.observation_revision,
        observation_digest=report.observation_digest,
        baseline_digest=report.baseline_digest,
        evaluation_report_digest=report.report_digest,
        evaluation_passed=True,
        evidence_kind=report.evidence_kind,  # type: ignore[arg-type]
        evidence_refs=report.evidence_refs,
        decided_by="harness",
        approved_by=approved_by,
        approved_at=approved_at,
        owner=owner,
        rollout_revision=rollout_revision,
        rollback=rollback,
        reason=reason,
    )


def structured_output_content_digest(payload: Mapping[str, Any]) -> str:
    normalized = {key: value for key, value in payload.items() if key != "content_digest"}
    return "sha256:" + sha256(_canonical_json_bytes(normalized)).hexdigest()


def _aggregate_metrics(
    results: Sequence[StructuredOutputEvaluationCaseResult],
) -> dict[str, float]:
    if not results:
        raise StructuredOutputEvaluationError("evaluation requires case results")
    accepted = [result for result in results if not result.provider_schema_rejected]
    repair_cases = [
        result
        for result in accepted
        if not result.first_pass_valid
    ]
    held_out = [result for result in accepted if result.split == "held_out_research"]
    if not accepted or not repair_cases or not held_out:
        raise StructuredOutputEvaluationError(
            "evaluation requires accepted, repair, and held-out Research cases"
        )
    latencies = sorted(result.latency_ms for result in results)
    return {
        "schema_validity_rate": _ratio(
            sum(result.final_valid for result in accepted), len(accepted)
        ),
        "first_pass_validity_rate": _ratio(
            sum(result.first_pass_valid for result in accepted), len(accepted)
        ),
        "repair_success_rate": _ratio(
            sum(result.final_valid for result in repair_cases), len(repair_cases)
        ),
        "answer_quality": _mean_required(
            result.answer_quality for result in held_out
        ),
        "evidence_grounding": _mean_required(
            result.evidence_grounding for result in held_out
        ),
        "citation_completeness": _mean_required(
            result.citation_completeness for result in held_out
        ),
        "provider_rejection_rate": _ratio(
            sum(result.provider_schema_rejected for result in results), len(results)
        ),
        "latency_p95_ms": _percentile_nearest_rank(latencies, 0.95),
        "average_total_tokens": sum(result.total_tokens for result in results)
        / len(results),
        "average_cost_usd": sum(result.cost_usd for result in results)
        / len(results),
    }


def _metric_gate(
    metric: str,
    *,
    actual: float,
    threshold: float,
    baseline: float,
    tolerance: float,
) -> StructuredOutputMetricGate:
    if metric in HIGHER_IS_BETTER_METRICS:
        direction: EvaluationMetricDirection = "min"
        threshold_passed = actual >= threshold
        regression_passed = actual >= baseline - tolerance
    elif metric in LOWER_IS_BETTER_METRICS:
        direction = "max"
        threshold_passed = actual <= threshold
        regression_passed = actual <= baseline + tolerance
    else:
        raise StructuredOutputEvaluationError(f"unsupported evaluation metric: {metric}")
    return StructuredOutputMetricGate(
        metric=metric,
        direction=direction,
        actual=actual,
        threshold=threshold,
        baseline=baseline,
        regression_tolerance=tolerance,
        passed=threshold_passed and regression_passed,
        threshold_passed=threshold_passed,
        regression_passed=regression_passed,
    )


def _verify_content_digest(payload: Mapping[str, Any]) -> None:
    declared = _required_digest(payload.get("content_digest"), "content_digest")
    expected = structured_output_content_digest(payload)
    if declared != expected:
        raise StructuredOutputEvaluationError(
            "evaluation evidence content_digest does not match content"
        )


def _require_schema_version(payload: Mapping[str, Any], expected: str) -> None:
    if payload.get("schema_version") != expected:
        raise StructuredOutputEvaluationError(
            f"unsupported evaluation schema_version; expected {expected}"
        )


def _load_json_object(path: str | Path) -> dict[str, Any]:
    resolved = Path(path)
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StructuredOutputEvaluationError(
            f"could not load structured-output evaluation evidence: {resolved}"
        ) from exc
    if not isinstance(payload, dict):
        raise StructuredOutputEvaluationError("evaluation evidence root must be an object")
    return payload


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _required_text(value: Any, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise StructuredOutputEvaluationError(
            f"{field_name} must be a non-empty string"
        )
    return text


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _required_object(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StructuredOutputEvaluationError(f"{field_name} must be an object")
    return dict(value)


def _object_tuple(value: Any, field_name: str) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        raise StructuredOutputEvaluationError(f"{field_name} must be a list")
    if not all(isinstance(item, dict) for item in value):
        raise StructuredOutputEvaluationError(
            f"{field_name} entries must be objects"
        )
    return tuple(dict(item) for item in value)


def _text_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise StructuredOutputEvaluationError(f"{field_name} must be a list")
    result = tuple(_required_text(item, field_name) for item in value)
    if len(set(result)) != len(result):
        raise StructuredOutputEvaluationError(
            f"{field_name} must not contain duplicates"
        )
    return result


def _required_text_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    result = _text_tuple(value, field_name)
    if not result:
        raise StructuredOutputEvaluationError(f"{field_name} must not be empty")
    return result


def _required_digest(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name)
    if len(text) != 71 or not text.startswith("sha256:"):
        raise StructuredOutputEvaluationError(
            f"{field_name} must be a sha256 digest"
        )
    try:
        int(text[7:], 16)
    except ValueError as exc:
        raise StructuredOutputEvaluationError(
            f"{field_name} must be a sha256 digest"
        ) from exc
    return text.casefold()


def _metric_mapping(value: Any, field_name: str) -> dict[str, float]:
    if not isinstance(value, Mapping):
        raise StructuredOutputEvaluationError(f"{field_name} must be an object")
    return {
        _required_text(key, field_name): _non_negative_number(item, field_name)
        for key, item in value.items()
    }


def _strict_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise StructuredOutputEvaluationError(f"{field_name} must be a boolean")
    return value


def _non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise StructuredOutputEvaluationError(
            f"{field_name} must be a non-negative integer"
        )
    return value


def _non_negative_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StructuredOutputEvaluationError(f"{field_name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise StructuredOutputEvaluationError(
            f"{field_name} must be finite and non-negative"
        )
    return result


def _unit_interval(value: Any, field_name: str) -> float:
    result = _non_negative_number(value, field_name)
    if result > 1.0:
        raise StructuredOutputEvaluationError(
            f"{field_name} must be between 0 and 1"
        )
    return result


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        raise StructuredOutputEvaluationError("metric denominator must be positive")
    return numerator / denominator


def _mean_required(values: Sequence[float | None] | Any) -> float:
    resolved = list(values)
    if not resolved or any(value is None for value in resolved):
        raise StructuredOutputEvaluationError("required quality metric is missing")
    return sum(float(value) for value in resolved) / len(resolved)


def _percentile_nearest_rank(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise StructuredOutputEvaluationError("latency metric requires observations")
    rank = max(1, math.ceil(percentile * len(values)))
    return float(values[rank - 1])


__all__ = [
    "HIGHER_IS_BETTER_METRICS",
    "LOWER_IS_BETTER_METRICS",
    "REQUIRED_EVALUATION_METRICS",
    "StructuredOutputEvaluationCaseResult",
    "StructuredOutputEvaluationError",
    "StructuredOutputEvaluationReport",
    "StructuredOutputEvaluationSuite",
    "StructuredOutputMetricGate",
    "StructuredOutputObservationSet",
    "StructuredOutputSchemaCorpus",
    "build_provider_structured_output_release",
    "load_structured_output_evaluation_suite",
    "structured_output_content_digest",
]
