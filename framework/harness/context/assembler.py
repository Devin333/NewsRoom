from __future__ import annotations

from dataclasses import replace
from typing import Any

from framework.harness.context.budget import ContextBudgetEstimator
from framework.harness.context.cache import ContextCachePolicyBuilder
from framework.harness.context.compression import ContextCompressor
from framework.harness.context.gates import ContextBudgetGate
from framework.harness.context.models import (
    CONTEXT_SEGMENT_ORDER,
    ContextBudget,
    ContextCacheScope,
    ContextCompressionLevel,
    ContextEnvelope,
    ContextSegment,
    ContextSegmentType,
)
from framework.harness.context.snapshot import ContextSnapshotStore
from framework.harness.control_plane.errors import HarnessValidationError


class ContextAssembler:
    def __init__(
        self,
        *,
        snapshot_store: ContextSnapshotStore | None = None,
        cache_policy_builder: ContextCachePolicyBuilder | None = None,
        budget_estimator: ContextBudgetEstimator | None = None,
        compressor: ContextCompressor | None = None,
    ) -> None:
        self.snapshot_store = snapshot_store or ContextSnapshotStore()
        self.cache_policy_builder = cache_policy_builder or ContextCachePolicyBuilder()
        self.budget_estimator = budget_estimator or ContextBudgetEstimator()
        self.compressor = compressor or ContextCompressor()
        self.events: list[dict[str, Any]] = []

    def assemble(self, request: dict[str, Any]) -> ContextEnvelope:
        self._event("context_assembly_started", request)
        budget = request.get("budget")
        if budget is None:
            budget = ContextBudget.safe_default()
        if isinstance(budget, dict):
            budget = ContextBudget(**budget)
        if not isinstance(budget, ContextBudget):
            raise HarnessValidationError("context budget must be ContextBudget")
        segments = self._collect_segments(request)
        envelope = ContextEnvelope(
            envelope_id=str(request.get("envelope_id", f"context://{request.get('run_id', 'run')}/{request.get('step_id', 'step')}")),
            run_id=request.get("run_id"),
            workflow_id=request.get("workflow_id"),
            step_id=request.get("step_id"),
            phase=request.get("phase"),
            worker_id=request.get("worker_id"),
            worker_type=request.get("worker_type"),
            segments=segments,
            budget=budget,
            stable_prefix=_stable_prefix_payload(segments),
            dynamic_tail=_dynamic_tail_payload(segments),
            artifact_refs=tuple(request.get("artifact_refs", ())),
            memory_refs=tuple(request.get("memory_refs", ())),
            evidence_refs=tuple(request.get("evidence_refs", ())),
            token_estimate=sum(segment.token_estimate for segment in segments),
            metadata=dict(request.get("metadata", {})),
        )
        self._event("context_budget_checked", {"usage": self.budget_estimator.estimate(envelope).to_dict()})
        if ContextBudgetGate().evaluate(envelope).passed is False:
            self._event("context_compression_requested", {"envelope_id": envelope.envelope_id})
            envelope = self._compress_dynamic_tail(envelope)
            self._event("context_compression_verified", {"envelope_id": envelope.envelope_id})
        cache_policy = self.cache_policy_builder.build(envelope, provider_hint=request.get("provider_hint"))
        envelope = replace(envelope, cache_policy=cache_policy)
        self._event("context_cache_key_created", cache_policy.to_dict())
        snapshot = self.snapshot_store.save(envelope)
        envelope = replace(envelope, snapshot_ref=snapshot.snapshot_id)
        self.snapshot_store.envelopes[envelope.envelope_id] = envelope
        self._event("context_snapshot_written", snapshot.to_dict())
        self._event("context_envelope_returned", {"envelope_id": envelope.envelope_id})
        return envelope

    def _collect_segments(self, request: dict[str, Any]) -> tuple[ContextSegment, ...]:
        configured = request.get("segments")
        if configured:
            segments = tuple(segment if isinstance(segment, ContextSegment) else ContextSegment(**segment) for segment in configured)
        else:
            segments = (
                _segment("global-policy", ContextSegmentType.GLOBAL_POLICY, "policy://global", "Harness controls routing, tools, memory, quality, and publication.", 80, ContextCacheScope.STABLE_PREFIX, ("policy://global",), {"global_policy": True, "forbidden_fields": ["next_step", "write_memory", "promote_skill"]}),
                _segment("workflow", ContextSegmentType.WORKFLOW, str(request.get("workflow_ref", "workflow://current")), "Workflow route table, current phase, step budget, and explicit gates.", 80, ContextCacheScope.STABLE_PREFIX, (str(request.get("workflow_ref", "workflow://current")),), {"route_table": request.get("allowed_routes", []), "budget": request.get("budget", {})}),
                _segment("worker-contract", ContextSegmentType.WORKER_CONTRACT, str(request.get("worker_contract_ref", "worker://contract")), "Worker input schema, output schema, tool allowlist, memory namespace policy, and forbidden fields.", 80, ContextCacheScope.STABLE_PREFIX, (str(request.get("worker_contract_ref", "worker://contract")),), {"input_schema": request.get("input_schema", {}), "output_schema": request.get("output_schema", {}), "tool_allowlist": request.get("allowed_tools", ()), "memory_namespace_policy": request.get("allowed_memory_namespaces", ())}),
                _segment("run-state", ContextSegmentType.RUN_STATE, str(request.get("run_state_ref", "run-state://current")), "Completed steps, failures, budget usage, checkpoint refs, and accepted artifact refs.", 120, ContextCacheScope.DYNAMIC_TAIL, tuple(request.get("run_state_refs", ("checkpoint://current",))), {"budget": request.get("budget", {})}),
                _segment("evidence-memory", ContextSegmentType.EVIDENCE_MEMORY, str(request.get("evidence_memory_ref", "evidence-memory://current")), "Accepted evidence, rejected evidence, memory hits, source refs, gap report, and retrieval rationale.", int(request.get("evidence_memory_tokens", 120)), ContextCacheScope.DYNAMIC_TAIL, tuple(request.get("source_refs", ("source://approved",))), {"source_refs": list(request.get("source_refs", ("source://approved",))), "artifact_refs": list(request.get("artifact_refs", ())), "content_markers": ["rag_result", "memory_hit"]}),
                _segment("current-task", ContextSegmentType.CURRENT_TASK, str(request.get("current_task_ref", "task://current")), str(request.get("current_instruction", "Produce structured candidate output for the current Harness step.")), int(request.get("current_task_tokens", 80)), ContextCacheScope.DYNAMIC_TAIL, tuple(request.get("input_refs", ("input://current",))), {}),
            )
        ordered_types = tuple(segment.segment_type for segment in segments)
        if ordered_types != CONTEXT_SEGMENT_ORDER[: len(segments)]:
            raise HarnessValidationError("context segments must be supplied in fixed six-part order")
        for segment in segments:
            self._event("context_segment_collected", segment.to_dict())
        return segments

    def _compress_dynamic_tail(self, envelope: ContextEnvelope) -> ContextEnvelope:
        compressed_segments = []
        for segment in envelope.segments:
            if segment.cache_scope == ContextCacheScope.STABLE_PREFIX:
                compressed_segments.append(segment)
                continue
            compressed, record = self.compressor.compress_segment(
                segment,
                run_id=envelope.run_id or "unknown-run",
                target_level=ContextCompressionLevel.C2_STEP_SUMMARY,
            )
            compressed_segments.append(compressed)
            self._event("context_compression_recorded", record.to_dict())
        return replace(
            envelope,
            segments=tuple(compressed_segments),
            stable_prefix=_stable_prefix_payload(tuple(compressed_segments)),
            dynamic_tail=_dynamic_tail_payload(tuple(compressed_segments)),
            token_estimate=sum(segment.token_estimate for segment in compressed_segments),
        )

    def _event(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append({"event_type": event_type, "payload": payload})


def _segment(
    segment_id: str,
    segment_type: ContextSegmentType,
    content_ref: str,
    summary: str,
    token_estimate: int,
    cache_scope: ContextCacheScope,
    provenance_refs: tuple[str, ...],
    metadata: dict[str, Any],
) -> ContextSegment:
    return ContextSegment(
        segment_id=segment_id,
        segment_type=segment_type,
        content_ref=content_ref,
        summary=summary,
        token_estimate=token_estimate,
        cache_scope=cache_scope,
        provenance_refs=provenance_refs,
        metadata=metadata,
    )


def _stable_prefix_payload(segments: tuple[ContextSegment, ...]) -> dict[str, Any]:
    return {
        segment.segment_type.value: segment.to_dict()
        for segment in segments
        if segment.cache_scope == ContextCacheScope.STABLE_PREFIX
    }


def _dynamic_tail_payload(segments: tuple[ContextSegment, ...]) -> dict[str, Any]:
    return {
        segment.segment_type.value: segment.to_dict()
        for segment in segments
        if segment.cache_scope == ContextCacheScope.DYNAMIC_TAIL
    }


__all__ = ["ContextAssembler"]
