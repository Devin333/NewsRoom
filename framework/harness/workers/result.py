from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from framework.events.canonical import checksum_for
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.side_effects.models import HarnessSideEffectIntent
from framework.shared.json import to_jsonable


class HarnessWorkerStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    WAITING_APPROVAL = "waiting_approval"


HARNESS_WORKER_EVIDENCE_SCHEMA = "newsroom.harness-worker-evidence/v1"


@dataclass(frozen=True, slots=True)
class HarnessWorkerEvidence:
    evidence_type: str
    payload: Mapping[str, Any]
    schema_version: str = HARNESS_WORKER_EVIDENCE_SCHEMA
    evidence_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        evidence_type = str(self.evidence_type).strip()
        if not evidence_type or evidence_type != self.evidence_type:
            raise HarnessValidationError(
                "worker evidence_type must be a non-blank trimmed string",
                code="invalid_worker_evidence",
            )
        if self.schema_version != HARNESS_WORKER_EVIDENCE_SCHEMA:
            raise HarnessValidationError(
                "worker evidence schema is unsupported",
                code="invalid_worker_evidence",
            )
        payload = _require_mapping(self.payload, "evidence.payload")
        object.__setattr__(self, "payload", payload)
        object.__setattr__(
            self,
            "evidence_checksum",
            checksum_for(self.checksum_projection()),
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "evidence_type": self.evidence_type,
            "payload": to_jsonable(self.payload),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.checksum_projection(),
            "evidence_checksum": self.evidence_checksum,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HarnessWorkerEvidence":
        if not isinstance(value, Mapping):
            raise HarnessValidationError("worker evidence must be an object")
        payload = dict(value)
        supplied = str(payload.pop("evidence_checksum", ""))
        if set(payload) != {"schema_version", "evidence_type", "payload"}:
            raise HarnessValidationError(
                "worker evidence fields are invalid",
                code="invalid_worker_evidence",
            )
        evidence = cls(**payload)
        if supplied != evidence.evidence_checksum:
            raise HarnessValidationError(
                "worker evidence checksum does not match",
                code="invalid_worker_evidence",
            )
        return evidence


FORBIDDEN_WORKER_RESULT_KEYS = frozenset(
    {
        "next_step",
        "next_route",
        "route",
        "route_to",
        "route_to_repair",
        "routing_decision",
        "retry",
        "replan",
        "halt_workflow",
        "complete_run",
        "quality_passed",
        "quality_score",
        "quality_verdict",
        "approval_decision",
        "approval_granted",
        "approval_status",
        "approved",
        "authorize",
        "authorization_decision",
        "tool_authorization",
        "tool_authorized",
        "write_memory",
        "memory_write",
        "memory_write_allowed",
        "memory_write_decision",
        "should_write_memory",
        "accept",
        "accepted",
        "publish",
        "publish_artifact",
        "publication_approved",
        "publication_decision",
        "should_publish",
        "published",
        "publication",
        "publish",
        "promote_skill",
        "promote",
        "promotion",
        "release",
        "release_skill",
        "production_version",
        "active_version",
        "active_skill",
        "active_package",
        "skip_eval",
        "auto_promote",
        "active",
        "artifact_class",
        "persistence",
        "retention_class",
        "retention",
        "persistence_mode",
        "persistence_decision",
        "materialization_mode",
        "storage_tier",
        "required_for_replay",
        "required_for_publication",
        "cache_eligible",
        "cache_ttl",
        "cache_ttl_seconds",
        "quota_override",
        "result_persistence",
        "result_retention",
        "persistence_policy_version",
    }
)

FORBIDDEN_WORKER_DECISION_PATHS_VERSION = "1"
_WORKER_RESULT_CHANNELS = ("output", "diagnostics", "metrics")
FORBIDDEN_WORKER_DECISION_PATHS = frozenset(
    f"{channel}.{key}"
    for channel in _WORKER_RESULT_CHANNELS
    for key in FORBIDDEN_WORKER_RESULT_KEYS
)


@dataclass(frozen=True)
class HarnessWorkerResult:
    status: HarnessWorkerStatus | str
    output: dict[str, Any] = field(default_factory=dict)
    artifacts: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    evidence: tuple[HarnessWorkerEvidence | Mapping[str, Any], ...] = ()
    error: str | None = None
    effect_intent: HarnessSideEffectIntent | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", HarnessWorkerStatus(self.status))
        output = _require_mapping(self.output, "output")
        diagnostics = _require_mapping(self.diagnostics, "diagnostics")
        metrics = _require_mapping(self.metrics, "metrics")
        forbidden_paths = _forbidden_worker_paths(
            ("output", output),
            ("diagnostics", diagnostics),
            ("metrics", metrics),
        )
        if forbidden_paths:
            forbidden = sorted({path.rsplit(".", 1)[-1] for path in forbidden_paths})
            raise HarnessValidationError(
                "worker result must not contain executable decision fields",
                code="worker_decision_field_rejected",
                details={
                    "code": "worker_decision_field_rejected",
                    "forbidden": forbidden,
                    "forbidden_paths": sorted(forbidden_paths),
                    "matrix_version": FORBIDDEN_WORKER_DECISION_PATHS_VERSION,
                },
            )
        object.__setattr__(self, "output", output)
        object.__setattr__(self, "artifacts", _candidate_artifact_refs(self.artifacts))
        object.__setattr__(self, "diagnostics", diagnostics)
        object.__setattr__(self, "metrics", metrics)
        evidence: list[HarnessWorkerEvidence] = []
        for item in self.evidence:
            if isinstance(item, HarnessWorkerEvidence):
                evidence.append(item)
            elif isinstance(item, Mapping):
                evidence.append(HarnessWorkerEvidence.from_dict(item))
            else:
                raise HarnessValidationError(
                    "worker evidence must contain typed values",
                    code="invalid_worker_evidence",
                )
        identities = [(item.evidence_type, item.evidence_checksum) for item in evidence]
        if len(identities) != len(set(identities)):
            raise HarnessValidationError(
                "worker evidence must contain unique entries",
                code="invalid_worker_evidence",
            )
        object.__setattr__(self, "evidence", tuple(evidence))
        if self.effect_intent is not None and not isinstance(
            self.effect_intent,
            HarnessSideEffectIntent,
        ):
            if isinstance(self.effect_intent, Mapping):
                object.__setattr__(
                    self,
                    "effect_intent",
                    HarnessSideEffectIntent.from_dict(self.effect_intent),
                )
            else:
                raise HarnessValidationError("effect_intent must be a typed HarnessSideEffectIntent")

    def to_dict(self) -> dict[str, Any]:
        payload = self.candidate_payload()
        if self.effect_intent is not None:
            payload["effect_intent"] = self.effect_intent.to_dict()
        return payload

    def candidate_payload(self) -> dict[str, Any]:
        """Return worker content without the self-referential intent envelope."""
        payload = {
            "status": self.status.value,
            "output": to_jsonable(self.output),
            "artifacts": list(self.artifacts),
            "diagnostics": to_jsonable(self.diagnostics),
            "metrics": to_jsonable(self.metrics),
            "error": self.error,
        }
        # Preserve the v1 candidate checksum for ordinary workers. Typed
        # evidence extends the payload only when a worker actually supplies it.
        if self.evidence:
            payload["evidence"] = [item.to_dict() for item in self.evidence]
        return payload

    @property
    def candidate_result_ref(self) -> str:
        return checksum_for(self.candidate_payload())


def _require_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise HarnessValidationError(f"worker result {field_name} must be an object")
    return {str(key): item for key, item in value.items()}


def _forbidden_worker_paths(*channels: tuple[str, Mapping[str, Any]]) -> tuple[str, ...]:
    paths: list[str] = []

    def visit(value: Any, path: str) -> None:
        if not isinstance(value, Mapping):
            return
        for raw_key, child in value.items():
            key = str(raw_key)
            normalized = key.casefold().replace("-", "_")
            child_path = f"{path}.{key}"
            if normalized.endswith("_observation") or normalized in {
                "observation",
                "observations",
            }:
                continue
            if normalized in FORBIDDEN_WORKER_RESULT_KEYS:
                paths.append(child_path)
                continue
            visit(child, child_path)

    for channel, value in channels:
        visit(value, channel)
    return tuple(paths)


def _candidate_artifact_refs(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        raise HarnessValidationError("worker result artifacts must be an array")
    refs: list[str] = []
    for ref in value:
        if not isinstance(ref, str) or not ref.strip() or ref.strip() != ref:
            raise HarnessValidationError(
                "worker result artifact refs must be non-blank strings",
                code="invalid_candidate_artifact_ref",
            )
        refs.append(ref)
    if len(set(refs)) != len(refs):
        raise HarnessValidationError(
            "worker result artifact refs must be unique",
            code="invalid_candidate_artifact_ref",
        )
    return tuple(refs)


def harness_worker_candidate_ref(value: HarnessWorkerResult | Mapping[str, Any]) -> str:
    if isinstance(value, HarnessWorkerResult):
        return value.candidate_result_ref
    if not isinstance(value, Mapping):
        raise TypeError("worker candidate payload must be a mapping or HarnessWorkerResult")
    payload = dict(value)
    payload.pop("effect_intent", None)
    required = {"status", "output", "artifacts", "diagnostics", "metrics", "error"}
    if set(payload) not in {frozenset(required), frozenset((*required, "evidence"))}:
        raise HarnessValidationError("worker candidate payload fields are invalid")
    return checksum_for(payload)


__all__ = [
    "FORBIDDEN_WORKER_DECISION_PATHS",
    "FORBIDDEN_WORKER_DECISION_PATHS_VERSION",
    "FORBIDDEN_WORKER_RESULT_KEYS",
    "HarnessWorkerResult",
    "HarnessWorkerEvidence",
    "HarnessWorkerStatus",
    "harness_worker_candidate_ref",
]
