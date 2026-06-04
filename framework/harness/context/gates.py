from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.harness.context.budget import ContextBudgetEstimator
from framework.harness.context.models import (
    CONTEXT_SEGMENT_ORDER,
    CONTROL_PLANE_PRESERVED_FIELDS,
    NON_COMPRESSIBLE_SEGMENT_TYPES,
    CompressionRecord,
    ContextCacheScope,
    ContextEnvelope,
    ContextSegment,
    ContextSegmentType,
    ContextSnapshot,
)


DYNAMIC_CONTENT_MARKERS = frozenset({"tool_result", "rag_result", "memory_hit", "user_note", "reader_payload"})
PRIVATE_MARKERS = frozenset({"private_memory", "unapproved_memory", "parent_raw_messages", "sibling_private_notes"})


@dataclass(frozen=True)
class ContextGateResult:
    gate_name: str
    passed: bool
    reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate_name,
            "passed": self.passed,
            "reason": self.reason,
            "details": self.details,
        }


class ContextSegmentOrderGate:
    gate_name = "context_segment_order"

    def evaluate(self, envelope: ContextEnvelope) -> ContextGateResult:
        actual = tuple(segment.segment_type for segment in envelope.segments)
        expected = CONTEXT_SEGMENT_ORDER[: len(actual)]
        passed = actual == expected
        return ContextGateResult(
            self.gate_name,
            passed,
            None if passed else "context segments are not in fixed six-part order",
            {"actual": [item.value for item in actual], "expected": [item.value for item in expected]},
        )


class ContextStablePrefixGate:
    gate_name = "context_stable_prefix"

    def evaluate(self, envelope: ContextEnvelope) -> ContextGateResult:
        violations = []
        for segment in envelope.segments:
            if segment.cache_scope != ContextCacheScope.STABLE_PREFIX:
                continue
            markers = set(segment.metadata.get("content_markers", ()))
            if markers.intersection(DYNAMIC_CONTENT_MARKERS):
                violations.append(segment.segment_id)
        return ContextGateResult(
            self.gate_name,
            not violations,
            None if not violations else "stable prefix contains dynamic content",
            {"violations": violations},
        )


class ContextSchemaPreservationGate:
    gate_name = "context_schema_preservation"

    def evaluate(self, record: CompressionRecord) -> ContextGateResult:
        lost_control_fields = sorted(set(record.lost_fields).intersection(CONTROL_PLANE_PRESERVED_FIELDS))
        return ContextGateResult(
            self.gate_name,
            not lost_control_fields,
            None if not lost_control_fields else "compression lost control-plane fields",
            {"lost_control_fields": lost_control_fields},
        )


class ContextBudgetGate:
    gate_name = "context_budget"

    def __init__(self) -> None:
        self.estimator = ContextBudgetEstimator()

    def evaluate(self, envelope: ContextEnvelope) -> ContextGateResult:
        budget = envelope.budget
        if budget is None:
            return ContextGateResult(self.gate_name, True, "no budget configured")
        usage = self.estimator.estimate(envelope)
        violations = {}
        if usage.input_tokens > budget.max_input_tokens:
            violations["input_tokens"] = {"used": usage.input_tokens, "max": budget.max_input_tokens}
        if usage.context_segments > budget.max_context_segments:
            violations["context_segments"] = {"used": usage.context_segments, "max": budget.max_context_segments}
        if usage.evidence_items > budget.max_evidence_items:
            violations["evidence_items"] = {"used": usage.evidence_items, "max": budget.max_evidence_items}
        if usage.memory_items > budget.max_memory_items:
            violations["memory_items"] = {"used": usage.memory_items, "max": budget.max_memory_items}
        if usage.artifact_refs > budget.max_artifact_refs:
            violations["artifact_refs"] = {"used": usage.artifact_refs, "max": budget.max_artifact_refs}
        return ContextGateResult(
            self.gate_name,
            not violations,
            None if not violations else "context budget exceeded",
            {"usage": usage.to_dict(), "violations": violations},
        )


class ContextProvenanceGate:
    gate_name = "context_provenance"

    def evaluate(self, envelope: ContextEnvelope) -> ContextGateResult:
        missing = [
            segment.segment_id
            for segment in envelope.segments
            if segment.segment_type in {ContextSegmentType.EVIDENCE_MEMORY, ContextSegmentType.RUN_STATE}
            and not segment.provenance_refs
        ]
        return ContextGateResult(
            self.gate_name,
            not missing,
            None if not missing else "context segment is missing provenance refs",
            {"missing": missing},
        )


class ContextPrivacyGate:
    gate_name = "context_privacy"

    def evaluate(self, envelope: ContextEnvelope) -> ContextGateResult:
        violations = []
        for segment in envelope.segments:
            markers = set(segment.metadata.get("content_markers", ()))
            if markers.intersection(PRIVATE_MARKERS) and not segment.metadata.get("consent", False):
                violations.append(segment.segment_id)
        return ContextGateResult(
            self.gate_name,
            not violations,
            None if not violations else "context contains private content without consent",
            {"violations": violations},
        )


class ContextCompressionLossGate:
    gate_name = "context_compression_loss"

    def evaluate(self, record: CompressionRecord) -> ContextGateResult:
        lost_control_fields = sorted(set(record.lost_fields).intersection(CONTROL_PLANE_PRESERVED_FIELDS))
        missing_preserved_refs = not record.preserved_refs
        return ContextGateResult(
            self.gate_name,
            not lost_control_fields and not missing_preserved_refs,
            None if not lost_control_fields and not missing_preserved_refs else "compression lost required refs or fields",
            {"lost_control_fields": lost_control_fields, "missing_preserved_refs": missing_preserved_refs},
        )


class ContextReplayGate:
    gate_name = "context_replay"

    def evaluate(self, snapshot: ContextSnapshot) -> ContextGateResult:
        passed = bool(snapshot.refs and snapshot.segment_refs and snapshot.assembled_prompt_ref and snapshot.checksum)
        return ContextGateResult(
            self.gate_name,
            passed,
            None if passed else "context snapshot is missing replay refs",
            {
                "refs": list(snapshot.refs),
                "segment_refs": list(snapshot.segment_refs),
                "assembled_prompt_ref": snapshot.assembled_prompt_ref,
            },
        )


class ContextCacheKeyGate:
    gate_name = "context_cache_key"

    def evaluate(self, envelope: ContextEnvelope) -> ContextGateResult:
        if envelope.cache_policy is None:
            return ContextGateResult(self.gate_name, False, "cache policy is missing")
        stable = {
            segment.segment_id
            for segment in envelope.segments
            if segment.cache_scope == ContextCacheScope.STABLE_PREFIX
        }
        policy_stable = set(envelope.cache_policy.stable_prefix_segments)
        passed = stable == policy_stable
        return ContextGateResult(
            self.gate_name,
            passed,
            None if passed else "cache key policy stable segments do not match envelope stable prefix",
            {"stable": sorted(stable), "policy_stable": sorted(policy_stable)},
        )


def non_compressible_segments(envelope: ContextEnvelope) -> tuple[ContextSegment, ...]:
    return tuple(segment for segment in envelope.segments if segment.segment_type in NON_COMPRESSIBLE_SEGMENT_TYPES)


__all__ = [
    "ContextBudgetGate",
    "ContextCacheKeyGate",
    "ContextCompressionLossGate",
    "ContextGateResult",
    "ContextPrivacyGate",
    "ContextProvenanceGate",
    "ContextReplayGate",
    "ContextSchemaPreservationGate",
    "ContextSegmentOrderGate",
    "ContextStablePrefixGate",
    "non_compressible_segments",
]
