from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from hashlib import sha256
from typing import Any

from framework.events.canonical import (
    canonical_json_bytes,
    checksum_for,
    thaw_canonical_json,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_application import (
    HarnessGraphControlPlaneRuntime,
)
from framework.harness.control_plane.graph_runtime import HarnessGraphActivity
from framework.harness.control_plane.graph_state import HarnessGraphState
from framework.harness.runtime.graph_result_runtime import HarnessGraphResultRuntime
from framework.harness.runtime.materializer import (
    MaterializationResult,
    ResultMaterializationObservation,
    ResultMaterializationOutcome,
    ResultMaterializer,
)
from framework.harness.runtime.result_models import (
    ArtifactClass,
    BoundedSummary,
    ContextPolicy,
    NodeResultBinding,
    NodeResultStatus,
    ResultProvenance,
    ResultSensitivity,
    RetentionClass,
)
from framework.harness.runtime.result_policy import (
    NodeResultRequest,
    PersistenceBudgetSnapshot,
)
from framework.harness.graph.model import NormalizedHarnessGraph
from framework.shared.time import ensure_utc, utc_now
from framework.shared.graph_identity import GraphExecutionIdentity
from framework.tool.models import (
    ToolCall,
    ToolDefinition,
    ToolObservation,
    ToolPolicy,
    ToolResultEnvelope,
    ToolRuntimeError,
    ToolSideEffectReceipt,
    ToolStatus,
)
from framework.tool.registry import ToolRegistry
from framework.tool.runtime.executor import ToolExecutor


TOOL_NODE_RESULT_SCHEMA = "newsroom.tool-node-result@1"
TOOL_RESPONSE_DOCUMENT_SCHEMA = "newsroom.tool-response-document@1"
TOOL_SIDE_EFFECT_EVIDENCE_SCHEMA = "newsroom.tool-side-effect-evidence@1"
HARNESS_BOUND_TOOL_RECEIPT_SCHEMA = (
    "newsroom.harness-bound-tool-side-effect-receipt@1"
)
_READ_ONLY_EFFECTS = frozenset({"", "none", "read_only"})


@dataclass(frozen=True, slots=True)
class HarnessBoundToolSideEffectReceipt:
    binding: NodeResultBinding
    tool_receipt: ToolSideEffectReceipt
    receipt_schema: str = HARNESS_BOUND_TOOL_RECEIPT_SCHEMA
    graph_binding_checksum: str = field(init=False)
    bound_receipt_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.binding, NodeResultBinding):
            raise TypeError("binding must be NodeResultBinding")
        if not isinstance(self.tool_receipt, ToolSideEffectReceipt):
            raise TypeError("tool_receipt must be ToolSideEffectReceipt")
        if self.receipt_schema != HARNESS_BOUND_TOOL_RECEIPT_SCHEMA:
            raise ToolRuntimeError("unsupported Harness-bound Tool receipt schema")
        binding_checksum = checksum_for(self.binding.to_dict())
        object.__setattr__(self, "graph_binding_checksum", binding_checksum)
        object.__setattr__(
            self,
            "bound_receipt_checksum",
            checksum_for(self.checksum_projection()),
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "receipt_schema": self.receipt_schema,
            "binding": self.binding.to_dict(),
            "graph_binding_checksum": self.graph_binding_checksum,
            "tool_receipt": self.tool_receipt.to_dict(),
        }

    def control_projection(self) -> dict[str, Any]:
        return {
            **self.tool_receipt.control_projection(),
            "tool_receipt_checksum": self.tool_receipt.receipt_checksum,
            "graph_binding_checksum": self.graph_binding_checksum,
            "bound_receipt_checksum": self.bound_receipt_checksum,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.checksum_projection(),
            "bound_receipt_checksum": self.bound_receipt_checksum,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "HarnessBoundToolSideEffectReceipt":
        if not isinstance(value, Mapping) or set(value) != {
            "receipt_schema",
            "binding",
            "graph_binding_checksum",
            "tool_receipt",
            "bound_receipt_checksum",
        }:
            raise ToolRuntimeError(
                "Harness-bound Tool receipt fields are invalid"
            )
        receipt = cls(
            receipt_schema=value["receipt_schema"],
            binding=NodeResultBinding.from_dict(value["binding"]),
            tool_receipt=ToolSideEffectReceipt.from_dict(value["tool_receipt"]),
        )
        if (
            value["graph_binding_checksum"] != receipt.graph_binding_checksum
            or value["bound_receipt_checksum"] != receipt.bound_receipt_checksum
        ):
            raise ToolRuntimeError(
                "Harness-bound Tool receipt checksum is invalid"
            )
        return receipt


@dataclass(frozen=True, slots=True)
class VerifiedHarnessToolSideEffectEvidence:
    receipt: HarnessBoundToolSideEffectReceipt
    response: Any
    response_media_type: str
    response_checksum: str


def verify_harness_tool_side_effect_evidence(
    value: Any,
    *,
    expected_binding: NodeResultBinding,
) -> VerifiedHarnessToolSideEffectEvidence:
    """Verify a decoded common-artifact side-effect evidence document."""

    if not isinstance(expected_binding, NodeResultBinding):
        raise TypeError("expected_binding must be NodeResultBinding")
    if not isinstance(value, Mapping) or set(value) != {
        "evidence_schema",
        "tool_id",
        "call_id",
        "tool_status",
        "response_media_type",
        "response_encoding",
        "response",
        "response_checksum",
        "receipt",
    }:
        raise ToolRuntimeError("Harness Tool side-effect evidence fields are invalid")
    if value["evidence_schema"] != TOOL_SIDE_EFFECT_EVIDENCE_SCHEMA:
        raise ToolRuntimeError("unsupported Harness Tool side-effect evidence schema")
    receipt = HarnessBoundToolSideEffectReceipt.from_dict(value["receipt"])
    if receipt.binding != expected_binding:
        raise ToolRuntimeError("Harness Tool side-effect evidence binding is invalid")
    response_media_type = str(value["response_media_type"]).strip().casefold()
    response = _decoded_response(
        value["response_encoding"],
        value["response"],
        response_media_type,
    )
    response_bytes = _response_bytes(response, response_media_type)
    response_checksum = f"sha256:{sha256(response_bytes).hexdigest()}"
    if (
        value["tool_id"] != receipt.tool_receipt.tool_id
        or value["call_id"] != receipt.tool_receipt.call_id
        or value["tool_status"] != receipt.tool_receipt.status
        or value["response_checksum"] != response_checksum
        or receipt.tool_receipt.response_checksum != response_checksum
    ):
        raise ToolRuntimeError("Harness Tool side-effect evidence integrity is invalid")
    return VerifiedHarnessToolSideEffectEvidence(
        receipt=receipt,
        response=response,
        response_media_type=response_media_type,
        response_checksum=response_checksum,
    )


@dataclass(frozen=True, slots=True)
class HarnessToolActivityResult:
    observation: ToolObservation | None
    materialization: MaterializationResult
    graph_state: HarnessGraphState
    recovered: bool = False

    def __post_init__(self) -> None:
        if self.observation is not None and not isinstance(
            self.observation,
            ToolObservation,
        ):
            raise TypeError("observation must be ToolObservation or None")
        if not isinstance(self.materialization, MaterializationResult):
            raise TypeError("materialization must be MaterializationResult")
        if not isinstance(self.graph_state, HarnessGraphState):
            raise TypeError("graph_state must be HarnessGraphState")
        if not isinstance(self.recovered, bool):
            raise TypeError("recovered must be boolean")


class HarnessToolResultAdapter:
    """Map completed ToolRuntime observations into Harness-owned result state."""

    def __init__(
        self,
        *,
        materializer: ResultMaterializer,
        graph_result_runtime: HarnessGraphResultRuntime,
        clock=utc_now,
    ) -> None:
        if not isinstance(materializer, ResultMaterializer):
            raise TypeError("materializer must be ResultMaterializer")
        if not isinstance(graph_result_runtime, HarnessGraphResultRuntime):
            raise TypeError("graph_result_runtime must be HarnessGraphResultRuntime")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._materializer = materializer
        self._graph_result_runtime = graph_result_runtime
        self._clock = clock

    def binding_for_activity(
        self,
        *,
        activity: HarnessGraphActivity,
        graph: NormalizedHarnessGraph,
        tenant_id: str,
        tenant_scope_ref: str,
        run_spec_checksum: str,
    ) -> NodeResultBinding:
        _require_activity(activity)
        return self._graph_result_runtime.binding_for_activity(
            activity_id=activity.activity_id,
            graph=graph,
            tenant_id=tenant_id,
            tenant_scope_ref=tenant_scope_ref,
            attempt_id=_graph_attempt_id(activity),
            run_spec_checksum=run_spec_checksum,
        )

    def request_from_observation(
        self,
        observation: ToolObservation,
        definition: ToolDefinition,
        *,
        binding: NodeResultBinding,
        created_at: datetime | None = None,
    ) -> NodeResultRequest:
        if not isinstance(binding, NodeResultBinding):
            raise TypeError("binding must be NodeResultBinding")
        envelope = ToolResultEnvelope.from_observation(observation, definition)
        contract = definition.result_persistence
        side_effect_free = definition.side_effect_value.casefold() in _READ_ONLY_EFFECTS
        bound_receipt = _bound_side_effect_receipt(
            envelope,
            binding=binding,
            side_effect_free=side_effect_free,
        )
        candidate, media_type = _candidate(
            envelope,
            side_effect_free=side_effect_free,
            bound_receipt=bound_receipt,
        )
        status = _node_status(envelope)
        required_for_replay = contract.required_for_replay or not side_effect_free
        artifact_class = (
            ArtifactClass.EVIDENCE
            if not side_effect_free
            else ArtifactClass(contract.artifact_class)
        )
        retention_class = (
            RetentionClass.EVIDENCE
            if not side_effect_free
            else RetentionClass(contract.retention_class)
        )
        reusable = (
            contract.reusable
            and side_effect_free
            and status is NodeResultStatus.SUCCEEDED
        )
        projection = dict(thaw_canonical_json(envelope.control_projection))
        if bound_receipt is not None:
            projection["side_effect_receipt"] = (
                bound_receipt.control_projection()
            )
        timestamp = ensure_utc(created_at or self._clock())
        output_schema_digest = checksum_for(
            {
                "schema": TOOL_NODE_RESULT_SCHEMA,
                "tool_id": definition.tool_id,
                "output_schema": definition.output_schema,
                "result_persistence": contract.to_dict(),
                "response_document_schema": (
                    TOOL_RESPONSE_DOCUMENT_SCHEMA
                    if side_effect_free and contract.is_json
                    else None
                ),
                "side_effect_evidence_schema": (
                    TOOL_SIDE_EFFECT_EVIDENCE_SCHEMA
                    if not side_effect_free
                    else None
                ),
            }
        )
        return NodeResultRequest(
            binding=binding,
            status=status,
            output_schema_ref=TOOL_NODE_RESULT_SCHEMA,
            output_schema_digest=output_schema_digest,
            candidate=candidate,
            media_type=media_type,
            summary=BoundedSummary.from_text(
                envelope.summary,
                complete=status is NodeResultStatus.SUCCEEDED,
            ),
            inline_projection=projection,
            inline_allowed_fields=tuple(sorted(projection)),
            provenance=ResultProvenance(
                producer_ref=definition.tool_id,
                producer_revision=definition.tool_id,
            ),
            artifact_class=artifact_class,
            retention_class=retention_class,
            sensitivity=ResultSensitivity(contract.sensitivity),
            required_for_replay=required_for_replay,
            required_for_publication=contract.required_for_publication,
            reusable=reusable,
            side_effect_free=side_effect_free,
            dependency_digest=(contract.dependency_digest if reusable else None),
            context_policy=ContextPolicy(contract.context_policy),
            created_at=timestamp,
        )

    def materialize_and_accept(
        self,
        observation: ToolObservation,
        definition: ToolDefinition,
        *,
        binding: NodeResultBinding,
        activity: HarnessGraphActivity,
        graph: NormalizedHarnessGraph,
        run_spec_checksum: str,
        occurred_at: datetime,
        budget: PersistenceBudgetSnapshot | None = None,
        context_fingerprint: str | None = None,
    ) -> HarnessToolActivityResult:
        _require_activity(activity)
        expected_binding = self.binding_for_activity(
            activity=activity,
            graph=graph,
            tenant_id=binding.tenant_id,
            tenant_scope_ref=binding.tenant_scope_ref,
            run_spec_checksum=run_spec_checksum,
        )
        if binding != expected_binding:
            raise HarnessValidationError(
                "Tool result binding does not match its Graph activity",
                code="graph_result_lineage_scope_mismatch",
            )
        request = self.request_from_observation(
            observation,
            definition,
            binding=binding,
            created_at=occurred_at,
        )
        materialization = self._materializer.materialize(request, budget=budget)
        graph_state = self._graph_result_runtime.accept_materialized_result(
            materialization.envelope,
            expected_binding=binding,
            activity_id=activity.activity_id,
            graph=graph,
            run_spec_checksum=run_spec_checksum,
            occurred_at=occurred_at,
            context_fingerprint=context_fingerprint,
        )
        return HarnessToolActivityResult(
            observation=observation,
            materialization=materialization,
            graph_state=graph_state,
        )

    def recover_and_accept(
        self,
        *,
        binding: NodeResultBinding,
        activity: HarnessGraphActivity,
        graph: NormalizedHarnessGraph,
        run_spec_checksum: str,
        occurred_at: datetime,
        context_fingerprint: str | None = None,
    ) -> HarnessToolActivityResult:
        """Finish Graph commit after materialization without re-executing a Tool."""

        _require_activity(activity)
        expected_binding = self.binding_for_activity(
            activity=activity,
            graph=graph,
            tenant_id=binding.tenant_id,
            tenant_scope_ref=binding.tenant_scope_ref,
            run_spec_checksum=run_spec_checksum,
        )
        if binding != expected_binding:
            raise HarnessValidationError(
                "Tool result binding does not match its Graph activity",
                code="graph_result_lineage_scope_mismatch",
            )
        envelope = self._materializer.recover(binding)
        if envelope is None:
            raise HarnessValidationError(
                "tool result recovery requires a committed attempt envelope",
                code="graph_result_recovery_missing",
            )
        graph_state = self._graph_result_runtime.accept_materialized_result(
            envelope,
            expected_binding=binding,
            activity_id=activity.activity_id,
            graph=graph,
            run_spec_checksum=run_spec_checksum,
            occurred_at=occurred_at,
            context_fingerprint=context_fingerprint,
        )
        return HarnessToolActivityResult(
            observation=None,
            materialization=MaterializationResult(
                envelope=envelope,
                observation=_recovery_observation(envelope),
            ),
            graph_state=graph_state,
            recovered=True,
        )


class HarnessToolActivityRuntime:
    """Production composition for Tool owner execution and Harness persistence."""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        executor: ToolExecutor,
        adapter: HarnessToolResultAdapter,
    ) -> None:
        if not isinstance(registry, ToolRegistry):
            raise TypeError("registry must be ToolRegistry")
        if not isinstance(executor, ToolExecutor):
            raise TypeError("executor must be ToolExecutor")
        if not executor.defers_result_persistence:
            raise ValueError(
                "Harness Tool activity runtime requires deferred Tool persistence"
            )
        if not isinstance(adapter, HarnessToolResultAdapter):
            raise TypeError("adapter must be HarnessToolResultAdapter")
        self._registry = registry
        self._executor = executor
        self._adapter = adapter

    def execute_and_accept(
        self,
        *,
        activity: HarnessGraphActivity,
        call: ToolCall,
        policy: ToolPolicy,
        graph: NormalizedHarnessGraph,
        tenant_id: str,
        tenant_scope_ref: str,
        run_spec_checksum: str,
        occurred_at: datetime,
        budget: PersistenceBudgetSnapshot | None = None,
        context_fingerprint: str | None = None,
    ) -> HarnessToolActivityResult:
        _require_activity(activity)
        if not isinstance(call, ToolCall):
            raise TypeError("call must be ToolCall")
        if not isinstance(policy, ToolPolicy):
            raise TypeError("policy must be ToolPolicy")
        definition = self._registry.get(call.tool_name).definition
        bound_call = _bind_call_to_activity(call, activity)
        binding = self._adapter.binding_for_activity(
            activity=activity,
            graph=graph,
            tenant_id=tenant_id,
            tenant_scope_ref=tenant_scope_ref,
            run_spec_checksum=run_spec_checksum,
        )
        observation = self._executor.execute(bound_call, policy)
        return self._adapter.materialize_and_accept(
            observation,
            definition,
            binding=binding,
            activity=activity,
            graph=graph,
            run_spec_checksum=run_spec_checksum,
            occurred_at=occurred_at,
            budget=budget,
            context_fingerprint=context_fingerprint,
        )

    def recover_and_accept(
        self,
        *,
        activity: HarnessGraphActivity,
        graph: NormalizedHarnessGraph,
        tenant_id: str,
        tenant_scope_ref: str,
        run_spec_checksum: str,
        occurred_at: datetime,
        context_fingerprint: str | None = None,
    ) -> HarnessToolActivityResult:
        binding = self._adapter.binding_for_activity(
            activity=activity,
            graph=graph,
            tenant_id=tenant_id,
            tenant_scope_ref=tenant_scope_ref,
            run_spec_checksum=run_spec_checksum,
        )
        return self._adapter.recover_and_accept(
            binding=binding,
            activity=activity,
            graph=graph,
            run_spec_checksum=run_spec_checksum,
            occurred_at=occurred_at,
            context_fingerprint=context_fingerprint,
        )


def build_harness_tool_activity_runtime(
    *,
    registry: ToolRegistry,
    materializer: ResultMaterializer,
    graph_runtime: HarnessGraphControlPlaneRuntime,
    approval_store: Any | None = None,
    secret_provider: Any | None = None,
    execution_environment: Any | None = None,
    trace_context: Any | None = None,
) -> HarnessToolActivityRuntime:
    """Wire the canonical production Tool path without a legacy artifact writer."""

    if not isinstance(graph_runtime, HarnessGraphControlPlaneRuntime):
        raise TypeError("graph_runtime must be HarnessGraphControlPlaneRuntime")
    executor = ToolExecutor(
        registry,
        approval_store=approval_store,
        secret_provider=secret_provider,
        execution_environment=execution_environment,
        trace_context=trace_context,
        defer_result_persistence=True,
    )
    adapter = HarnessToolResultAdapter(
        materializer=materializer,
        graph_result_runtime=HarnessGraphResultRuntime(graph_runtime),
    )
    return HarnessToolActivityRuntime(
        registry=registry,
        executor=executor,
        adapter=adapter,
    )


def _candidate(
    envelope: ToolResultEnvelope,
    *,
    side_effect_free: bool,
    bound_receipt: HarnessBoundToolSideEffectReceipt | None,
) -> tuple[Any, str]:
    if side_effect_free:
        if envelope.media_type == "application/json" or envelope.media_type.endswith(
            "+json"
        ):
            return (
                {
                    "response_schema": TOOL_RESPONSE_DOCUMENT_SCHEMA,
                    "tool_id": envelope.tool_id,
                    "call_id": envelope.call_id,
                    "tool_status": envelope.status,
                    "response": thaw_canonical_json(envelope.response),
                    "response_checksum": envelope.response_checksum,
                },
                envelope.media_type,
            )
        return envelope.response, envelope.media_type
    if bound_receipt is None:
        raise ToolRuntimeError("side-effect Tool result is missing its receipt")
    response_encoding, response = _encoded_response(
        envelope.response,
        envelope.media_type,
    )
    return (
        {
            "evidence_schema": TOOL_SIDE_EFFECT_EVIDENCE_SCHEMA,
            "tool_id": envelope.tool_id,
            "call_id": envelope.call_id,
            "tool_status": envelope.status,
            "response_media_type": envelope.media_type,
            "response_encoding": response_encoding,
            "response": response,
            "response_checksum": envelope.response_checksum,
            "receipt": bound_receipt.to_dict(),
        },
        "application/json",
    )


def _bound_side_effect_receipt(
    envelope: ToolResultEnvelope,
    *,
    binding: NodeResultBinding,
    side_effect_free: bool,
) -> HarnessBoundToolSideEffectReceipt | None:
    if side_effect_free:
        if envelope.side_effect_receipt is not None:
            raise ToolRuntimeError(
                "read-only Tool result cannot carry a side-effect receipt"
            )
        return None
    if envelope.side_effect_receipt is None:
        raise ToolRuntimeError("side-effect Tool result is missing its receipt")
    return HarnessBoundToolSideEffectReceipt(
        binding=binding,
        tool_receipt=envelope.side_effect_receipt,
    )


def _encoded_response(value: Any, media_type: str) -> tuple[str, Any]:
    if media_type == "application/json" or media_type.endswith("+json"):
        return "json", thaw_canonical_json(value)
    if media_type.startswith("text/"):
        return "text", value
    return "base64", base64.b64encode(value).decode("ascii")


def _decoded_response(encoding: Any, value: Any, media_type: str) -> Any:
    if encoding == "json" and (
        media_type == "application/json" or media_type.endswith("+json")
    ):
        return value
    if encoding == "text" and media_type.startswith("text/"):
        if not isinstance(value, str):
            raise ToolRuntimeError("Tool evidence text response is invalid")
        return value
    if (
        encoding == "base64"
        and not media_type.startswith("text/")
        and media_type != "application/json"
        and not media_type.endswith("+json")
    ):
        try:
            return base64.b64decode(value, validate=True)
        except (TypeError, ValueError, base64.binascii.Error) as exc:
            raise ToolRuntimeError(
                "Tool evidence binary response is invalid"
            ) from exc
    raise ToolRuntimeError("Tool evidence encoding conflicts with media_type")


def _response_bytes(value: Any, media_type: str) -> bytes:
    if media_type == "application/json" or media_type.endswith("+json"):
        return canonical_json_bytes(value)
    if media_type.startswith("text/"):
        if not isinstance(value, str):
            raise ToolRuntimeError("Tool evidence text response is invalid")
        return value.encode("utf-8")
    if not isinstance(value, bytes):
        raise ToolRuntimeError("Tool evidence binary response is invalid")
    return value


def _node_status(envelope: ToolResultEnvelope) -> NodeResultStatus:
    status = ToolStatus(envelope.status)
    if status is ToolStatus.SUCCEEDED:
        return NodeResultStatus.SUCCEEDED
    if status is ToolStatus.SKIPPED:
        return NodeResultStatus.SKIPPED
    if envelope.indeterminate or (
        envelope.timeout and envelope.termination_confirmed is not True
    ):
        return NodeResultStatus.HALTED
    return NodeResultStatus.FAILED


def _graph_attempt_id(activity: HarnessGraphActivity) -> str:
    return f"tool_{activity.activity_id.removeprefix('hga_')}"


def _bind_call_to_activity(
    call: ToolCall,
    activity: HarnessGraphActivity,
) -> ToolCall:
    configured = call.metadata.get("idempotency_key")
    if configured is not None and configured != activity.idempotency_key:
        raise HarnessValidationError(
            "Tool call idempotency identity conflicts with its Graph activity",
            code="graph_activity_identity_mismatch",
        )
    graph_identity = GraphExecutionIdentity(
        run_id=activity.run_id,
        graph_id=activity.graph_ref.graph_id,
        graph_version=activity.graph_ref.identity_version,
        graph_ref=activity.graph_ref.identity_ref.exact_ref,
        graph_checksum=activity.graph_ref.checksum,
        node_id=activity.node_id,
        node_instance_id=activity.node_instance_id,
        activity_id=activity.activity_id,
        attempt=activity.attempt,
    )
    if call.graph_identity is not None and call.graph_identity != graph_identity:
        raise HarnessValidationError(
            "Tool call Graph identity conflicts with its Graph activity",
            code="graph_activity_identity_mismatch",
        )
    return replace(
        call,
        metadata={
            **call.metadata,
            "idempotency_key": activity.idempotency_key,
        },
        graph_identity=graph_identity,
    )


def _require_activity(activity: Any) -> HarnessGraphActivity:
    if not isinstance(activity, HarnessGraphActivity):
        raise TypeError("activity must be HarnessGraphActivity")
    return activity


def _recovery_observation(envelope):
    return ResultMaterializationObservation(
        binding=envelope.binding,
        outcome=ResultMaterializationOutcome.SUCCEEDED,
        mode=envelope.persistence_decision.mode,
        candidate_bytes=envelope.metrics.candidate_bytes,
        reason=envelope.persistence_decision.reason,
    )


__all__ = [
    "HARNESS_BOUND_TOOL_RECEIPT_SCHEMA",
    "HarnessBoundToolSideEffectReceipt",
    "HarnessToolActivityResult",
    "HarnessToolActivityRuntime",
    "HarnessToolResultAdapter",
    "TOOL_NODE_RESULT_SCHEMA",
    "TOOL_RESPONSE_DOCUMENT_SCHEMA",
    "TOOL_SIDE_EFFECT_EVIDENCE_SCHEMA",
    "VerifiedHarnessToolSideEffectEvidence",
    "build_harness_tool_activity_runtime",
    "verify_harness_tool_side_effect_evidence",
]
