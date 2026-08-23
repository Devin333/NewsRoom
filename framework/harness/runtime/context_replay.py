from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from framework.harness.context.compaction_models import (
    ContextCompactionActionResult,
    ContextCompactionPlan,
)
from framework.harness.context.durable_store import (
    ContextDurableRefs,
    ContextVerifiedArtifactStore,
)
from framework.harness.context.planning_models import (
    ContextCompactionPlanningResult,
    ContextPhysicalAdmissionEvidence,
)
from framework.harness.context.verified_records import (
    ContextCompressionRecordV2,
    ContextSemanticSnapshot,
)
from framework.harness.context.verification import ContextAggregateVerificationResult
from framework.harness.control_plane.event import HarnessEvent, HarnessEventType
from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.json import stable_json_dumps, to_jsonable


@dataclass(frozen=True)
class ContextCompactionReplayReport:
    source_snapshot_id: str
    result_snapshot_id: str | None
    plan_id: str | None
    record_id: str | None
    prepared_fingerprint: str | None
    verification_classification: str
    side_effects_replayed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_snapshot_id": self.source_snapshot_id,
            "result_snapshot_id": self.result_snapshot_id,
            "plan_id": self.plan_id,
            "record_id": self.record_id,
            "prepared_fingerprint": self.prepared_fingerprint,
            "verification_classification": self.verification_classification,
            "side_effects_replayed": self.side_effects_replayed,
        }


class ContextCompactionReplayReader:
    """Validate durable v2 context evidence without replaying side effects."""

    def __init__(self, store: ContextVerifiedArtifactStore) -> None:
        if not isinstance(store, ContextVerifiedArtifactStore):
            raise HarnessValidationError("store must be ContextVerifiedArtifactStore")
        self._store = store

    def replay(
        self,
        refs: ContextDurableRefs | Mapping[str, Any],
        *,
        activation_event: HarnessEvent | None = None,
    ) -> ContextCompactionReplayReport:
        durable_refs = (
            refs if isinstance(refs, ContextDurableRefs) else ContextDurableRefs.from_dict(refs)
        )
        source_ref = _required_ref(durable_refs.source_snapshot, "source_snapshot")
        admission_ref = _required_ref(durable_refs.initial_admission, "initial_admission")
        planning_ref = _required_ref(durable_refs.planning_result, "planning_result")
        source = ContextSemanticSnapshot.from_dict(
            self._store.read_artifact_payload(
                source_ref,
                expected_type="context-source-snapshot",
            )
        )
        initial = ContextPhysicalAdmissionEvidence.from_dict(
            self._store.read_artifact_payload(
                admission_ref,
                expected_type="context-physical-admission",
            )
        )
        planning = ContextCompactionPlanningResult.from_dict(
            self._store.read_artifact_payload(
                planning_ref,
                expected_type="context-compaction-planning-result",
            )
        )
        _assert_snapshot_ref(source_ref, source)
        _assert_admission_ref(admission_ref, initial)
        if (
            initial.source_snapshot_id != source.snapshot_id
            or initial.source_snapshot_checksum != source.checksum
            or planning.source_snapshot_id != source.snapshot_id
            or planning.source_snapshot_checksum != source.checksum
            or planning.admission_evidence_id != initial.evidence_id
        ):
            raise HarnessValidationError("context replay source cross-reference is invalid")

        if planning.plan is None:
            self._validate_no_compaction_event(
                activation_event,
                source=source,
                initial=initial,
            )
            return ContextCompactionReplayReport(
                source_snapshot_id=source.snapshot_id,
                result_snapshot_id=source.snapshot_id if initial.admitted else None,
                plan_id=None,
                record_id=None,
                prepared_fingerprint=initial.prepared_fingerprint if initial.admitted else None,
                verification_classification=(
                    "versioned_no_compaction_evidence" if initial.admitted else "rejected"
                ),
            )

        plan_ref = _required_ref(durable_refs.plan, "plan")
        plan = ContextCompactionPlan.from_dict(
            self._store.read_artifact_payload(
                plan_ref,
                expected_type="context-compaction-plan",
            )
        )
        if plan.plan_id != planning.plan.plan_id or plan.identity_checksum != planning.plan.identity_checksum:
            raise HarnessValidationError("context replay plan is not pinned by planning result")
        if plan.source_snapshot_id != source.snapshot_id or plan.initial_admission_ref != initial.evidence_id:
            raise HarnessValidationError("context replay plan source binding is invalid")

        action_results = tuple(
            ContextCompactionActionResult.from_dict(
                self._store.read_artifact_payload(
                    ref,
                    expected_type="context-compaction-action-result",
                )
            )
            for ref in durable_refs.action_results
        )
        if any(result.source_snapshot_id != source.snapshot_id for result in action_results):
            raise HarnessValidationError("context replay action source binding is invalid")

        result_ref = _required_ref(durable_refs.result_snapshot, "result_snapshot")
        final_ref = _required_ref(durable_refs.final_admission, "final_admission")
        aggregate_ref = _required_ref(
            durable_refs.aggregate_verification,
            "aggregate_verification",
        )
        record_ref = _required_ref(durable_refs.compression_record, "compression_record")
        result = ContextSemanticSnapshot.from_dict(
            self._store.read_artifact_payload(
                result_ref,
                expected_type="context-result-snapshot",
            )
        )
        final = ContextPhysicalAdmissionEvidence.from_dict(
            self._store.read_artifact_payload(
                final_ref,
                expected_type="context-physical-admission",
            )
        )
        aggregate = ContextAggregateVerificationResult.from_dict(
            self._store.read_artifact_payload(
                aggregate_ref,
                expected_type="context-aggregate-verification",
            )
        )
        record = ContextCompressionRecordV2.from_dict(
            self._store.read_artifact_payload(
                record_ref,
                expected_type="context-compression-record-v2",
            )
        )
        _assert_snapshot_ref(result_ref, result)
        _assert_admission_ref(final_ref, final)
        if (
            result.parent_snapshot_id != source.snapshot_id
            or final.source_snapshot_id != result.snapshot_id
            or final.source_snapshot_checksum != result.checksum
            or aggregate.source_snapshot_id != source.snapshot_id
            or aggregate.result_snapshot_id != result.snapshot_id
            or aggregate.physical_admission_evidence_id != final.evidence_id
            or record.source_snapshot_id != source.snapshot_id
            or record.result_snapshot_id != result.snapshot_id
            or record.plan_id != plan.plan_id
            or record.prepared_fingerprint != final.prepared_fingerprint
            or record.initial_admission_evidence_id != initial.evidence_id
            or record.final_admission_evidence_id != final.evidence_id
            or record.materialization_revision != final.materialization_revision
            or tuple(action.to_dict() for action in record.action_results)
            != tuple(action.to_dict() for action in action_results)
            or _canonical(record.gate_results)
            != _canonical(tuple(gate.to_dict() for gate in aggregate.gates))
        ):
            raise HarnessValidationError("context replay v2 cross-reference is invalid")
        for summary_ref in record.summary_refs:
            self._verify_checksum_bound_artifact(summary_ref)

        classification = (
            "versioned_verified_evidence" if aggregate.dispatch_authorized else "rejected"
        )
        if activation_event is not None:
            self._validate_activation_event(
                activation_event,
                source=source,
                result=result,
                record_ref=record_ref.ref,
                aggregate=aggregate,
                final=final,
            )
            if classification != "versioned_verified_evidence":
                raise HarnessValidationError(
                    "rejected compaction result must not have an activation event"
                )
        return ContextCompactionReplayReport(
            source_snapshot_id=source.snapshot_id,
            result_snapshot_id=result.snapshot_id,
            plan_id=plan.plan_id,
            record_id=record.record_id,
            prepared_fingerprint=final.prepared_fingerprint,
            verification_classification=classification,
        )

    def _verify_checksum_bound_artifact(self, ref: str) -> None:
        if "#sha256=" not in ref:
            raise HarnessValidationError("summary artifact ref must contain a checksum fragment")
        base_ref, expected = ref.rsplit("#sha256=", 1)
        if not base_ref or len(expected) != 64:
            raise HarnessValidationError("summary artifact checksum fragment is invalid")
        # ContextVerifiedArtifactStore verifies the same wrapper checksum for
        # its own artifacts. Summary artifacts are externally owned, so only
        # validate their checksum-bound immutable envelope here.
        self._store.read_checksum_bound_artifact(ref)

    @staticmethod
    def _validate_activation_event(
        event: HarnessEvent,
        *,
        source: ContextSemanticSnapshot,
        result: ContextSemanticSnapshot,
        record_ref: str,
        aggregate: ContextAggregateVerificationResult,
        final: ContextPhysicalAdmissionEvidence,
    ) -> None:
        if event.event_type is not HarnessEventType.CONTEXT_COMPACTION_VERIFIED:
            raise HarnessValidationError("context activation event type is invalid")
        payload = event.payload
        if (
            payload.get("source_snapshot_id") != source.snapshot_id
            or payload.get("result_snapshot_id") != result.snapshot_id
            or payload.get("record_ref") != record_ref
            or payload.get("prepared_fingerprint") != final.prepared_fingerprint
            or not aggregate.dispatch_authorized
        ):
            raise HarnessValidationError("context activation event is stale or invalid")

    @staticmethod
    def _validate_no_compaction_event(
        event: HarnessEvent | None,
        *,
        source: ContextSemanticSnapshot,
        initial: ContextPhysicalAdmissionEvidence,
    ) -> None:
        if event is None:
            return
        if event.event_type is not HarnessEventType.CONTEXT_COMPACTION_PLANNED:
            raise HarnessValidationError("no-compaction event type is invalid")
        if (
            event.payload.get("source_snapshot_id") != source.snapshot_id
            or event.payload.get("status") != "no_compaction_required"
            or event.payload.get("initial_admission_id") != initial.evidence_id
            or not initial.admitted
        ):
            raise HarnessValidationError("no-compaction event is stale or invalid")


def _required_ref(value, field: str):
    if value is None:
        raise HarnessValidationError(f"context replay requires {field} ref")
    return value


def _assert_snapshot_ref(reference, snapshot: ContextSemanticSnapshot) -> None:
    metadata = reference.metadata
    if (
        metadata.get("snapshot_id") != snapshot.snapshot_id
        or metadata.get("snapshot_checksum") != snapshot.checksum
    ):
        raise HarnessValidationError("context snapshot artifact metadata is invalid")


def _assert_admission_ref(reference, evidence: ContextPhysicalAdmissionEvidence) -> None:
    metadata = reference.metadata
    if metadata.get("evidence_id") != evidence.evidence_id:
        raise HarnessValidationError("context admission artifact metadata is invalid")


def _canonical(value: Any) -> str:
    return stable_json_dumps(to_jsonable(value))


__all__ = [
    "ContextCompactionReplayReader",
    "ContextCompactionReplayReport",
]
