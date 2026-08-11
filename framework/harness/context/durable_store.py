from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

from framework.harness.artifacts import ArtifactPort, ArtifactRef, ArtifactWriteRequest
from framework.harness.context.compaction_models import ContextCompactionActionResult, ContextCompactionPlan
from framework.harness.context.planning_models import (
    ContextCompactionPlanningResult,
    ContextPhysicalAdmissionEvidence,
)
from framework.harness.context.verified_records import (
    ContextCompressionRecordV2,
    ContextSemanticSnapshot,
)
from framework.harness.context.verification import ContextAggregateVerificationResult
from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.json import stable_json_dumps


@dataclass(frozen=True)
class ContextDurableRefs:
    """Immutable, ref-only projection of one context compaction attempt."""

    source_snapshot: ArtifactRef | None = None
    initial_admission: ArtifactRef | None = None
    planning_result: ArtifactRef | None = None
    plan: ArtifactRef | None = None
    action_results: tuple[ArtifactRef, ...] = ()
    result_snapshot: ArtifactRef | None = None
    final_admission: ArtifactRef | None = None
    aggregate_verification: ArtifactRef | None = None
    compression_record: ArtifactRef | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "source_snapshot",
            "initial_admission",
            "planning_result",
            "plan",
            "result_snapshot",
            "final_admission",
            "aggregate_verification",
            "compression_record",
        ):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, ArtifactRef):
                raise HarnessValidationError(f"{field_name} must be an ArtifactRef")
        action_results = tuple(self.action_results)
        if not all(isinstance(value, ArtifactRef) for value in action_results):
            raise HarnessValidationError("action_results must contain ArtifactRef values")
        object.__setattr__(self, "action_results", action_results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_snapshot": _artifact_projection(self.source_snapshot),
            "initial_admission": _artifact_projection(self.initial_admission),
            "planning_result": _artifact_projection(self.planning_result),
            "plan": _artifact_projection(self.plan),
            "action_results": [_artifact_projection(value) for value in self.action_results],
            "result_snapshot": _artifact_projection(self.result_snapshot),
            "final_admission": _artifact_projection(self.final_admission),
            "aggregate_verification": _artifact_projection(self.aggregate_verification),
            "compression_record": _artifact_projection(self.compression_record),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContextDurableRefs":
        if not isinstance(value, Mapping):
            raise HarnessValidationError("ContextDurableRefs payload must be an object")
        expected = {
            "source_snapshot",
            "initial_admission",
            "planning_result",
            "plan",
            "action_results",
            "result_snapshot",
            "final_admission",
            "aggregate_verification",
            "compression_record",
        }
        if set(value) != expected:
            raise HarnessValidationError("ContextDurableRefs fields are invalid")
        action_results = value["action_results"]
        if not isinstance(action_results, (list, tuple)):
            raise HarnessValidationError("ContextDurableRefs.action_results must be a list")
        return cls(
            source_snapshot=_optional_artifact(value["source_snapshot"]),
            initial_admission=_optional_artifact(value["initial_admission"]),
            planning_result=_optional_artifact(value["planning_result"]),
            plan=_optional_artifact(value["plan"]),
            action_results=tuple(_artifact_from_projection(item) for item in action_results),
            result_snapshot=_optional_artifact(value["result_snapshot"]),
            final_admission=_optional_artifact(value["final_admission"]),
            aggregate_verification=_optional_artifact(value["aggregate_verification"]),
            compression_record=_optional_artifact(value["compression_record"]),
        )


@runtime_checkable
class ContextVerifiedStorePort(Protocol):
    def save_snapshot(self, snapshot: ContextSemanticSnapshot) -> ArtifactRef: ...

    def save_planning_result(
        self, result: ContextCompactionPlanningResult
    ) -> ArtifactRef: ...

    def save_plan(self, plan: ContextCompactionPlan) -> ArtifactRef: ...

    def save_action_result(self, result: ContextCompactionActionResult) -> ArtifactRef: ...

    def save_admission(
        self, evidence: ContextPhysicalAdmissionEvidence
    ) -> ArtifactRef: ...

    def save_aggregate_verification(
        self, result: ContextAggregateVerificationResult
    ) -> ArtifactRef: ...

    def save_compression_record(
        self, record: ContextCompressionRecordV2
    ) -> ArtifactRef: ...


class ContextVerifiedArtifactStore:
    """Persist checksum-derived context facts as immutable Harness artifacts."""

    def __init__(self, artifact_port: ArtifactPort) -> None:
        if not isinstance(artifact_port, ArtifactPort):
            raise HarnessValidationError("artifact_port must implement ArtifactPort")
        self._artifact_port = artifact_port

    def save_snapshot(self, snapshot: ContextSemanticSnapshot) -> ArtifactRef:
        if not isinstance(snapshot, ContextSemanticSnapshot):
            raise HarnessValidationError("snapshot must be ContextSemanticSnapshot")
        kind = "source" if snapshot.snapshot_kind.value == "source" else "result"
        return self._write(
            artifact_type=f"context-{kind}-snapshot",
            identity=snapshot.checksum,
            payload=snapshot.to_dict(),
            metadata={
                "run_id": snapshot.run_id,
                "snapshot_id": snapshot.snapshot_id,
                "snapshot_checksum": snapshot.checksum,
                "context_ref_only": True,
            },
        )

    def save_planning_result(
        self, result: ContextCompactionPlanningResult
    ) -> ArtifactRef:
        if not isinstance(result, ContextCompactionPlanningResult):
            raise HarnessValidationError("result must be ContextCompactionPlanningResult")
        return self._write(
            artifact_type="context-compaction-planning-result",
            identity=result.checksum,
            payload=result.to_dict(),
            metadata={
                "source_snapshot_id": result.source_snapshot_id,
                "source_snapshot_checksum": result.source_snapshot_checksum,
                "context_ref_only": True,
            },
        )

    def save_plan(self, plan: ContextCompactionPlan) -> ArtifactRef:
        if not isinstance(plan, ContextCompactionPlan):
            raise HarnessValidationError("plan must be ContextCompactionPlan")
        return self._write(
            artifact_type="context-compaction-plan",
            identity=plan.identity_checksum,
            payload=plan.to_dict(),
            metadata={
                "source_snapshot_id": plan.source_snapshot_id,
                "source_snapshot_checksum": plan.source_snapshot_checksum,
                "plan_id": plan.plan_id,
                "context_ref_only": True,
            },
        )

    def save_action_result(self, result: ContextCompactionActionResult) -> ArtifactRef:
        if not isinstance(result, ContextCompactionActionResult):
            raise HarnessValidationError("result must be ContextCompactionActionResult")
        payload = result.to_dict()
        return self._write(
            artifact_type="context-compaction-action-result",
            identity=_payload_checksum(payload),
            payload=payload,
            metadata={
                "source_snapshot_id": result.source_snapshot_id,
                "action_id": result.action.action_id,
                "action_type": result.action.action_type.value,
                "context_ref_only": True,
            },
        )

    def save_admission(
        self, evidence: ContextPhysicalAdmissionEvidence
    ) -> ArtifactRef:
        if not isinstance(evidence, ContextPhysicalAdmissionEvidence):
            raise HarnessValidationError("evidence must be ContextPhysicalAdmissionEvidence")
        return self._write(
            artifact_type="context-physical-admission",
            identity=evidence.checksum,
            payload=evidence.to_dict(),
            metadata={
                "source_snapshot_id": evidence.source_snapshot_id,
                "source_snapshot_checksum": evidence.source_snapshot_checksum,
                "evidence_id": evidence.evidence_id,
                "context_ref_only": True,
            },
        )

    def save_aggregate_verification(
        self, result: ContextAggregateVerificationResult
    ) -> ArtifactRef:
        if not isinstance(result, ContextAggregateVerificationResult):
            raise HarnessValidationError(
                "result must be ContextAggregateVerificationResult"
            )
        payload = result.to_dict()
        return self._write(
            artifact_type="context-aggregate-verification",
            identity=_payload_checksum(payload),
            payload=payload,
            metadata={
                "source_snapshot_id": result.source_snapshot_id,
                "result_snapshot_id": result.result_snapshot_id,
                "physical_admission_evidence_id": result.physical_admission_evidence_id,
                "context_ref_only": True,
            },
        )

    def save_compression_record(
        self, record: ContextCompressionRecordV2
    ) -> ArtifactRef:
        if not isinstance(record, ContextCompressionRecordV2):
            raise HarnessValidationError("record must be ContextCompressionRecordV2")
        return self._write(
            artifact_type="context-compression-record-v2",
            identity=record.checksum,
            payload=record.to_dict(),
            metadata={
                "run_id": record.run_id,
                "record_id": record.record_id,
                "source_snapshot_id": record.source_snapshot_id,
                "result_snapshot_id": record.result_snapshot_id,
                "context_ref_only": True,
            },
        )

    def read_artifact_payload(
        self,
        artifact: ArtifactRef | Mapping[str, Any],
        *,
        expected_type: str,
    ) -> dict[str, Any]:
        reference = _artifact_from_projection(artifact)
        expected_prefix = f"{expected_type}-"
        if not reference.artifact_type.startswith(expected_prefix):
            raise HarnessValidationError("context artifact type does not match reference")
        envelope = self._artifact_port.read_artifact(reference.ref)
        if not isinstance(envelope, Mapping):
            raise HarnessValidationError("context artifact envelope must be an object")
        if str(envelope.get("artifact_type", "")) != reference.artifact_type:
            raise HarnessValidationError("context artifact envelope type is invalid")
        if str(envelope.get("media_type", "")) != reference.media_type:
            raise HarnessValidationError("context artifact media type is invalid")
        if _payload_checksum(dict(envelope)) != reference.checksum:
            raise HarnessValidationError("context artifact checksum mismatch")
        payload = envelope.get("payload")
        if not isinstance(payload, Mapping):
            raise HarnessValidationError("context artifact payload must be an object")
        return dict(payload)

    def read_checksum_bound_artifact(self, ref: str) -> dict[str, Any]:
        """Read an externally-owned immutable envelope and verify its checksum fragment."""
        if not isinstance(ref, str) or "#sha256=" not in ref:
            raise HarnessValidationError(
                "checksum-bound artifact ref must contain a checksum fragment"
            )
        base_ref, expected = ref.rsplit("#sha256=", 1)
        if not base_ref or len(expected) != 64:
            raise HarnessValidationError("checksum-bound artifact checksum is invalid")
        envelope = self._artifact_port.read_artifact(base_ref)
        if not isinstance(envelope, Mapping):
            raise HarnessValidationError("checksum-bound artifact envelope must be an object")
        actual = _payload_checksum(dict(envelope)).removeprefix("sha256:")
        if actual != expected:
            raise HarnessValidationError("checksum-bound artifact checksum mismatch")
        return dict(envelope)

    def _write(
        self,
        *,
        artifact_type: str,
        identity: str | None,
        payload: Mapping[str, Any],
        metadata: Mapping[str, Any],
    ) -> ArtifactRef:
        if not isinstance(identity, str) or not identity.startswith("sha256:"):
            raise HarnessValidationError("context artifact identity must be a sha256 checksum")
        suffix = identity.removeprefix("sha256:")
        if len(suffix) != 64:
            raise HarnessValidationError("context artifact identity checksum is invalid")
        request = ArtifactWriteRequest(
            artifact_type=f"{artifact_type}-{suffix}",
            payload=dict(payload),
            metadata={**dict(metadata), "identity_checksum": identity},
        )
        stored = self._artifact_port.write_artifact(request)
        if not isinstance(stored, ArtifactRef):
            raise HarnessValidationError("context artifact port must return ArtifactRef")
        if not stored.ref or not stored.checksum.startswith("sha256:"):
            raise HarnessValidationError("context artifact ref must include a sha256 checksum")
        return stored


def _artifact_projection(value: ArtifactRef | None) -> dict[str, Any] | None:
    return value.to_dict() if value is not None else None


def _artifact_from_projection(value: ArtifactRef | Mapping[str, Any]) -> ArtifactRef:
    if isinstance(value, ArtifactRef):
        return value
    if not isinstance(value, Mapping):
        raise HarnessValidationError("artifact reference must be an object")
    expected = {"ref", "artifact_type", "checksum", "media_type", "metadata"}
    if set(value) != expected:
        raise HarnessValidationError("artifact reference fields are invalid")
    metadata = value["metadata"]
    if not isinstance(metadata, Mapping):
        raise HarnessValidationError("artifact reference metadata must be an object")
    return ArtifactRef(
        ref=str(value["ref"]),
        artifact_type=str(value["artifact_type"]),
        checksum=str(value["checksum"]),
        media_type=str(value["media_type"]),
        metadata=dict(metadata),
    )


def _optional_artifact(value: Any) -> ArtifactRef | None:
    return None if value is None else _artifact_from_projection(value)


def _payload_checksum(payload: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(stable_json_dumps(dict(payload)).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


__all__ = [
    "ContextDurableRefs",
    "ContextVerifiedArtifactStore",
    "ContextVerifiedStorePort",
]
