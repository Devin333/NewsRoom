from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

from framework.harness.context.budget import ContextBudgetEstimator
from framework.harness.context.cache import ContextCachePolicyBuilder
from framework.harness.context.compaction_models import (
    ContextCompactionActionType,
    ContextCompactionPolicy,
)
from framework.harness.context.gates import ContextBudgetGate
from framework.harness.context.materializer import (
    ContextGroupMaterializer,
    ContextMaterializationRequest,
)
from framework.harness.context.models import (
    CONTEXT_SEGMENT_ORDER,
    ContextBudget,
    ContextCacheScope,
    ContextEnvelope,
    ContextSegment,
    ContextSegmentType,
)
from framework.harness.context.snapshot import ContextSnapshotStore
from framework.harness.control_plane.errors import HarnessValidationError


@runtime_checkable
class _ContextCompactionRuntimePort(Protocol):
    def run(self, request: Any) -> Any: ...


class ContextAssembler:
    """Build compatibility envelopes and delegate lossy changes to Harness runtime."""

    def __init__(
        self,
        *,
        snapshot_store: ContextSnapshotStore | None = None,
        cache_policy_builder: ContextCachePolicyBuilder | None = None,
        budget_estimator: ContextBudgetEstimator | None = None,
        compaction_runtime: _ContextCompactionRuntimePort | None = None,
        compaction_runtime_factory: (
            Callable[[ContextEnvelope, Mapping[str, Any]], _ContextCompactionRuntimePort]
            | None
        ) = None,
        deployment_id: str | None = None,
        physical_profile_revision: str | None = None,
        compaction_policy: ContextCompactionPolicy | None = None,
    ) -> None:
        if compaction_runtime is not None and not isinstance(
            compaction_runtime, _ContextCompactionRuntimePort
        ):
            raise HarnessValidationError(
                "compaction_runtime must be ContextCompactionRuntime"
            )
        if compaction_runtime_factory is not None and not callable(
            compaction_runtime_factory
        ):
            raise HarnessValidationError("compaction_runtime_factory must be callable")
        if compaction_runtime is not None and compaction_runtime_factory is not None:
            raise HarnessValidationError(
                "configure compaction_runtime or compaction_runtime_factory, not both"
            )
        if compaction_policy is not None and not isinstance(
            compaction_policy, ContextCompactionPolicy
        ):
            raise HarnessValidationError(
                "compaction_policy must be ContextCompactionPolicy"
            )
        self.snapshot_store = snapshot_store or ContextSnapshotStore()
        self.cache_policy_builder = cache_policy_builder or ContextCachePolicyBuilder()
        self.budget_estimator = budget_estimator or ContextBudgetEstimator()
        self.compaction_runtime = compaction_runtime
        self.compaction_runtime_factory = compaction_runtime_factory
        self.deployment_id = _optional_text(deployment_id, "deployment_id")
        self.physical_profile_revision = _optional_text(
            physical_profile_revision,
            "physical_profile_revision",
        )
        self.compaction_policy = compaction_policy
        self.events: list[dict[str, Any]] = []

    def assemble(self, request: dict[str, Any]) -> ContextEnvelope:
        self._event("context_assembly_started", request)
        budget = _budget_from_request(request)
        segments = self._collect_segments(request)
        envelope = ContextEnvelope(
            envelope_id=str(
                request.get(
                    "envelope_id",
                    f"context://{request.get('run_id', 'run')}/{request.get('step_id', 'step')}",
                )
            ),
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
        estimate = self.budget_estimator.estimate(envelope)
        self._event("context_budget_checked", {"usage": estimate.to_dict()})
        envelope = self._verify_or_reject_context(
            envelope,
            request=request,
            legacy_budget_passed=ContextBudgetGate().evaluate(envelope).passed,
        )
        cache_policy = self.cache_policy_builder.build(
            envelope,
            provider_hint=request.get("provider_hint"),
        )
        envelope = replace(envelope, cache_policy=cache_policy)
        self._event("context_cache_key_created", cache_policy.to_dict())
        envelope, snapshot = self.snapshot_store.save_bound(envelope)
        self._event("context_snapshot_written", snapshot.to_dict())
        self._event("context_envelope_returned", {"envelope_id": envelope.envelope_id})
        return envelope

    def _verify_or_reject_context(
        self,
        envelope: ContextEnvelope,
        *,
        request: Mapping[str, Any],
        legacy_budget_passed: bool,
    ) -> ContextEnvelope:
        compaction_runtime = self.compaction_runtime
        if self.compaction_runtime_factory is not None:
            compaction_runtime = self.compaction_runtime_factory(envelope, request)
            if not isinstance(compaction_runtime, _ContextCompactionRuntimePort):
                raise HarnessValidationError(
                    "compaction_runtime_factory must return ContextCompactionRuntime"
                )
        if compaction_runtime is None:
            if not legacy_budget_passed:
                self._event(
                    "context_compaction_rejected",
                    {
                        "envelope_id": envelope.envelope_id,
                        "reason_code": "verified_context_runtime_not_configured",
                    },
                )
                raise HarnessValidationError(
                    "context exceeds the legacy budget and requires a verified compaction runtime"
                )
            # The old envelope/snapshot path remains readable for callers that have
            # not bound a physical request, but it cannot authorize dispatch.
            return replace(
                envelope,
                metadata={
                    **envelope.metadata,
                    "context_verification_classification": "legacy_unverified",
                    "context_dispatch_authorized": False,
                },
            )

        policy = _policy_from_request(
            request,
            configured=self.compaction_policy,
            budget=envelope.budget,
        )
        deployment_id = _required_runtime_value(
            request.get("deployment_id", self.deployment_id),
            "deployment_id",
        )
        profile_revision = _required_runtime_value(
            request.get("physical_profile_revision", self.physical_profile_revision),
            "physical_profile_revision",
        )
        source = ContextGroupMaterializer().materialize(
            ContextMaterializationRequest(
                run_id=str(envelope.run_id or "context-assembly"),
                step_id=envelope.step_id,
                task_binding_ref=str(
                    request.get("current_task_ref", f"task://{envelope.envelope_id}")
                ),
                policy_revision=policy.policy_revision,
                physical_profile_revision=profile_revision,
                segments=envelope.segments,
                messages=tuple(request.get("messages", ())),
                evidence_items=tuple(request.get("evidence_items", ())),
                authorized_tools=tuple(request.get("authorized_tools", ())),
                output_contract_ref=request.get("output_contract_ref"),
                requires_output_contract=bool(request.get("requires_output_contract", False)),
                retry_state_ref=request.get("retry_state_ref"),
                control_decision_refs=tuple(request.get("control_decision_refs", ())),
            )
        )
        result = compaction_runtime.run(
            _runtime_request(
                source_snapshot=source,
                policy=policy,
                deployment_id=deployment_id,
            )
        )
        self._event(
            "context_runtime_completed",
            {
                "envelope_id": envelope.envelope_id,
                "status": result.status.value,
                "reason_code": result.reason_code,
                "source_snapshot_id": result.source_snapshot.snapshot_id,
                "result_snapshot_id": (
                    result.result_snapshot.snapshot_id if result.result_snapshot else None
                ),
                "activation_event_id": result.activation_event_id,
                "durable_refs": result.durable_refs.to_dict(),
            },
        )
        if not result.dispatch_authorized:
            self._event(
                "context_compaction_rejected",
                {
                    "envelope_id": envelope.envelope_id,
                    "status": result.status.value,
                    "reason_code": result.reason_code,
                    "source_snapshot_id": result.source_snapshot.snapshot_id,
                },
            )
            raise HarnessValidationError(
                "verified context runtime did not authorize provider dispatch",
                details={
                    "status": result.status.value,
                    "reason_code": result.reason_code,
                    "source_snapshot_id": result.source_snapshot.snapshot_id,
                },
            )
        evidence = result.final_admission or result.initial_admission
        assert evidence is not None
        return replace(
            envelope,
            token_estimate=evidence.input_tokens,
            metadata={
                **envelope.metadata,
                "context_verification_classification": (
                    "versioned_verified_evidence"
                    if result.result_snapshot is not None
                    and result.result_snapshot.snapshot_id != result.source_snapshot.snapshot_id
                    else "versioned_no_compaction_evidence"
                ),
                # The envelope is a legacy compatibility projection, not the
                # exact provider request admitted by the runtime. Downstream
                # dispatch must rematerialize and match this fingerprint.
                "context_dispatch_authorized": False,
                "context_dispatch_authorization_required": True,
                "context_prepared_fingerprint": evidence.prepared_fingerprint,
                "context_activation_event_id": result.activation_event_id,
                "context_source_snapshot_id": result.source_snapshot.snapshot_id,
                "context_source_snapshot_checksum": result.source_snapshot.checksum,
                "context_result_snapshot_id": (
                    result.result_snapshot.snapshot_id
                    if result.result_snapshot is not None
                    else result.source_snapshot.snapshot_id
                ),
                "context_result_snapshot_checksum": (
                    result.result_snapshot.checksum
                    if result.result_snapshot is not None
                    else result.source_snapshot.checksum
                ),
                "context_durable_refs": result.durable_refs.to_dict(),
                "context_projection": "legacy_envelope_ref_only",
            },
        )

    def _collect_segments(self, request: dict[str, Any]) -> tuple[ContextSegment, ...]:
        configured = request.get("segments")
        if configured:
            segments = tuple(
                segment
                if isinstance(segment, ContextSegment)
                else ContextSegment(**segment)
                for segment in configured
            )
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

    def compression_record_projections(
        self,
        *,
        envelope_id: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        records: list[dict[str, Any]] = []
        for event in self.events:
            if event.get("event_type") != "context_runtime_completed":
                continue
            payload = event.get("payload")
            if not isinstance(payload, Mapping):
                continue
            if envelope_id is not None and payload.get("envelope_id") != envelope_id:
                continue
            durable_refs = payload.get("durable_refs")
            if not isinstance(durable_refs, Mapping):
                continue
            record_ref = durable_refs.get("compression_record")
            if not isinstance(record_ref, Mapping):
                continue
            records.append(
                {
                    "schema_revision": "newsroom.context-compression-record-ref/v2",
                    "record_ref": dict(record_ref),
                    "source_snapshot_ref": durable_refs.get("source_snapshot"),
                    "result_snapshot_ref": durable_refs.get("result_snapshot"),
                    "aggregate_verification_ref": durable_refs.get(
                        "aggregate_verification"
                    ),
                    "final_admission_ref": durable_refs.get("final_admission"),
                    "activation_event_id": payload.get("activation_event_id"),
                    "status": payload.get("status"),
                    "reason_code": payload.get("reason_code"),
                }
            )
        return tuple(records)

    def _event(self, event_type: str, payload: Mapping[str, Any]) -> None:
        self.events.append({"event_type": event_type, "payload": dict(payload)})


def _budget_from_request(request: Mapping[str, Any]) -> ContextBudget:
    budget = request.get("budget") or ContextBudget.safe_default()
    if isinstance(budget, Mapping):
        budget = ContextBudget(**budget)
    if not isinstance(budget, ContextBudget):
        raise HarnessValidationError("context budget must be ContextBudget")
    return budget


def _runtime_request(**values: Any) -> Any:
    # Delayed import prevents assembler -> runtime -> ports -> rag -> assembler.
    from framework.harness.context.runtime import ContextCompactionRuntimeRequest

    return ContextCompactionRuntimeRequest(**values)


def _policy_from_request(
    request: Mapping[str, Any],
    *,
    configured: ContextCompactionPolicy | None,
    budget: ContextBudget | None,
) -> ContextCompactionPolicy:
    raw = request.get("compaction_policy", configured)
    if isinstance(raw, Mapping):
        raw = ContextCompactionPolicy.from_dict(raw)
    if raw is not None:
        if not isinstance(raw, ContextCompactionPolicy):
            raise HarnessValidationError("compaction_policy must be ContextCompactionPolicy")
        return raw
    assert budget is not None
    return ContextCompactionPolicy(
        policy_revision="newsroom.context-compaction-policy/default-v1",
        action_order=(
            ContextCompactionActionType.DROP_RECONSTRUCTABLE_GROUP,
            ContextCompactionActionType.REPLACE_WITH_REFERENCE,
            ContextCompactionActionType.REDUCE_AUTHORIZED_TOOL_SET,
            ContextCompactionActionType.SELECT_EVIDENCE_SPANS,
            ContextCompactionActionType.COMPACT_OLD_CONVERSATION,
        ),
        max_actions=5,
        max_summary_calls=0,
        max_replans=1,
        max_llm_calls=0,
        max_input_tokens=budget.max_input_tokens,
        max_cost_usd=0.0,
        max_turns=5,
    )


def _required_runtime_value(value: Any, field: str) -> str:
    value = _optional_text(value, field)
    if value is None:
        raise HarnessValidationError(f"{field} is required with a compaction runtime")
    return value


def _optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise HarnessValidationError(f"{field} must be a non-empty string when provided")
    return value.strip()


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
        provenance_refs=provenance_refs,
        cache_scope=cache_scope,
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
