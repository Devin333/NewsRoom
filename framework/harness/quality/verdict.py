from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterable

from framework.events.canonical import checksum_for
from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.json import to_jsonable

if TYPE_CHECKING:
    from framework.harness.control_plane.gates import HarnessGateResult


HARNESS_VERDICT_AGGREGATION_VERSION = "1"
HARNESS_VERIFICATION_EVIDENCE_SCHEMA = "newsroom.harness-verification-evidence/v1"


@dataclass(frozen=True)
class HarnessQualityVerdict:
    passed: bool
    score: float | None = None
    issues: tuple[str, ...] = ()
    repair_hints: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.passed, bool):
            raise HarnessValidationError("passed must be a boolean")
        if self.score is not None:
            if not isinstance(self.score, int | float) or isinstance(self.score, bool):
                raise HarnessValidationError("score must be a number between 0 and 1")
            if not 0 <= self.score <= 1:
                raise HarnessValidationError("score must be between 0 and 1")
            object.__setattr__(self, "score", float(self.score))
        if not isinstance(self.issues, list | tuple):
            raise HarnessValidationError("issues must be a sequence")
        if not isinstance(self.repair_hints, list | tuple):
            raise HarnessValidationError("repair_hints must be a sequence")
        if not isinstance(self.metadata, Mapping):
            raise HarnessValidationError("metadata must be an object")
        object.__setattr__(self, "issues", tuple(str(issue) for issue in self.issues))
        object.__setattr__(self, "repair_hints", tuple(str(hint) for hint in self.repair_hints))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "score": self.score,
            "issues": list(self.issues),
            "repair_hints": list(self.repair_hints),
            "metadata": to_jsonable(self.metadata),
        }


def aggregate_gate_verdict(
    gate_results: Iterable["HarnessGateResult"],
    *,
    declared_gate_reference: str | None,
) -> HarnessQualityVerdict | None:
    results = tuple(gate_results)
    if declared_gate_reference is None:
        return None
    if not results:
        raise HarnessValidationError("a declared quality gate requires deterministic results")

    result_evidence = tuple(gate_result_evidence(result) for result in results)
    passed = all(result.passed for result in results)
    scores = tuple(
        float(score)
        for result in results
        if isinstance((score := result.details.get("score")), int | float)
        and not isinstance(score, bool)
    )
    issues = tuple(
        result.reason or f"{result.gate_name} failed"
        for result in results
        if not result.passed
    )
    repair_hints = tuple(
        str(hint)
        for result in results
        for hint in _string_sequence(result.details.get("repair_hints", ()))
        if not result.passed
    )
    return HarnessQualityVerdict(
        passed=passed,
        score=min(scores) if scores else (1.0 if passed else 0.0),
        issues=issues,
        repair_hints=repair_hints,
        metadata={
            "aggregation_version": HARNESS_VERDICT_AGGREGATION_VERSION,
            "declared_gate_reference": declared_gate_reference,
            "gate_result_ref": checksum_for(result_evidence),
            "gate_references": [
                evidence["reference"]
                for result in results
                if isinstance((evidence := result.details.get("harness_gate")), Mapping)
                and isinstance(evidence.get("reference"), str)
            ],
        },
    )


def gate_result_evidence(result: Any) -> dict[str, Any]:
    payload = result.to_dict() if callable(getattr(result, "to_dict", None)) else result
    if not isinstance(payload, Mapping):
        raise HarnessValidationError("gate result evidence requires an object")
    gate = payload.get("gate")
    passed = payload.get("passed")
    details = payload.get("details")
    harness_gate = details.get("harness_gate") if isinstance(details, Mapping) else None
    if not isinstance(gate, str) or not gate.strip() or not isinstance(passed, bool):
        raise HarnessValidationError("gate result evidence requires gate and boolean passed")
    if not isinstance(harness_gate, Mapping):
        raise HarnessValidationError("gate result evidence requires exact Harness identity")
    evidence = {
        "gate": gate.strip(),
        "passed": passed,
        "reference": harness_gate.get("reference"),
        "input_ref": harness_gate.get("input_ref"),
        "result_ref": harness_gate.get("result_ref"),
        "reason_code": harness_gate.get("reason_code"),
    }
    if not all(isinstance(evidence[key], str) and evidence[key] for key in (
        "reference",
        "input_ref",
        "result_ref",
        "reason_code",
    )):
        raise HarnessValidationError("gate result evidence is incomplete")
    score = details.get("score") if isinstance(details, Mapping) else None
    if isinstance(score, int | float) and not isinstance(score, bool):
        evidence["score"] = float(score)
    return evidence


def quality_verdict_evidence(verdict: HarnessQualityVerdict) -> dict[str, Any]:
    if not isinstance(verdict, HarnessQualityVerdict):
        raise TypeError("verdict must be HarnessQualityVerdict")
    metadata = verdict.metadata
    return {
        "passed": verdict.passed,
        "score": verdict.score,
        "aggregation_version": metadata.get("aggregation_version"),
        "declared_gate_reference": metadata.get("declared_gate_reference"),
        "gate_result_ref": metadata.get("gate_result_ref"),
        "gate_references": list(metadata.get("gate_references", ())),
    }


def verification_evidence(
    gate_results: Iterable["HarnessGateResult"],
    verdict: HarnessQualityVerdict | None,
) -> dict[str, Any]:
    return {
        "schema": HARNESS_VERIFICATION_EVIDENCE_SCHEMA,
        "gate_results": [gate_result_evidence(result) for result in gate_results],
        "quality_verdict": None if verdict is None else quality_verdict_evidence(verdict),
    }


def _string_sequence(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list | tuple | set | frozenset):
        return tuple(str(item) for item in value)
    raise HarnessValidationError("repair_hints must be a string sequence")


__all__ = [
    "HARNESS_VERDICT_AGGREGATION_VERSION",
    "HARNESS_VERIFICATION_EVIDENCE_SCHEMA",
    "HarnessQualityVerdict",
    "aggregate_gate_verdict",
    "gate_result_evidence",
    "quality_verdict_evidence",
    "verification_evidence",
]
