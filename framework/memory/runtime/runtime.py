from __future__ import annotations

from time import perf_counter
from typing import Any, Callable
from uuid import uuid4

from dataclasses import replace

from framework.governance import PolicyDecision
from framework.events import TraceContext
from framework.memory.diagnostics.trace import MemoryTraceEvent, MemoryTraceRecorder
from framework.memory.models import (
    MemoryConsolidationRequest,
    MemoryConsolidationResult,
    MemoryForgetRequest,
    MemoryForgetResult,
    MemoryKind,
    MemoryOperationTrace,
    MemoryQuery,
    MemoryRecallResult,
    MemoryRecord,
    MemoryScope,
    MemoryWriteMode,
    MemoryWriteRequest,
    MemoryWriteResult,
)
from framework.memory.models.record import coerce_memory_record
from framework.memory.policy import DEFAULT_GRAPH_MEMORY_POLICY, MemoryPolicy
from framework.memory.runtime.context_assembler import MemoryContextAssembler
from framework.memory.runtime.consolidation import MemoryConsolidator
from framework.memory.runtime.forgetting import MemoryForgettingEngine
from framework.memory.runtime.invalidation import MemoryInvalidationEngine
from framework.memory.runtime.lifecycle import MemoryLifecycleManager
from framework.memory.runtime.promotion import MemoryPromotionEngine
from framework.memory.runtime.recall import MemoryRecallStrategy, SimpleMemoryRecallStrategy
from framework.memory.runtime.writer import MemoryWriter
from framework.memory.stores import MemoryStore
from framework.shared.graph_identity import GraphExecutionIdentity


class MemoryRuntime:
    def __init__(
        self,
        store: MemoryStore,
        *,
        policy: MemoryPolicy | None = None,
        recall_strategy: MemoryRecallStrategy | None = None,
        assembler: MemoryContextAssembler | None = None,
        writer: MemoryWriter | None = None,
        consolidator: MemoryConsolidator | None = None,
        forgetting_engine: MemoryForgettingEngine | None = None,
        promotion_engine: MemoryPromotionEngine | None = None,
        invalidation_engine: MemoryInvalidationEngine | None = None,
        lifecycle_manager: MemoryLifecycleManager | None = None,
        trace_context: TraceContext | None = None,
        trace_recorder: MemoryTraceRecorder | None = None,
    ) -> None:
        self.store = store
        self.policy = policy or DEFAULT_GRAPH_MEMORY_POLICY
        self.recall_strategy = recall_strategy or SimpleMemoryRecallStrategy()
        self.assembler = assembler or MemoryContextAssembler()
        self.writer = writer or MemoryWriter()
        self.consolidator = consolidator or MemoryConsolidator()
        self.forgetting_engine = forgetting_engine or MemoryForgettingEngine()
        self.promotion_engine = promotion_engine or MemoryPromotionEngine()
        self.invalidation_engine = invalidation_engine or MemoryInvalidationEngine()
        self.lifecycle_manager = lifecycle_manager or MemoryLifecycleManager()
        self.trace_context = trace_context
        self.trace_recorder = trace_recorder

    def recall(
        self,
        query: MemoryQuery | dict[str, Any] | str,
        *,
        policy: MemoryPolicy | None = None,
    ) -> MemoryRecallResult:
        started = perf_counter()
        memory_query = _coerce_query(query)
        operation = self._start_operation_trace(
            operation_type="recall",
            namespace=getattr(memory_query, "namespace", None),
            query=memory_query.query,
            metadata={"limit": memory_query.limit},
        )
        decision = memory_policy_decision(
            "memory.recall",
            namespace=getattr(memory_query, "namespace", None),
            tenant_id=getattr(memory_query, "tenant_id", None),
        )
        if not decision.allowed:
            operation = self._finish_recall_trace(
                operation,
                started=started,
                policy_decision=decision.to_dict(),
                results=[],
                candidate_count=0,
                filtered_count=0,
            )
            result = MemoryRecallResult(
                query=memory_query,
                diagnostics={"errors": [decision.reason]},
                policy_decision=decision.to_dict(),
                operation_trace=operation,
                error_envelope=_memory_error_envelope(
                    "MemoryPolicyDenied",
                    decision.reason,
                    details={"policy_decision": decision.to_dict()},
                ),
            )
            self._record_operation_trace(operation)
            return result
        result = self.recall_strategy.recall(
            memory_query,
            store=self.store,
            policy=policy or self.policy,
            assembler=self.assembler,
        )
        operation = self._finish_recall_trace(
            operation,
            started=started,
            policy_decision=decision.to_dict(),
            results=result.results,
            candidate_count=_recall_candidate_count(result),
            filtered_count=_recall_filtered_count(result),
        )
        result = replace(result, policy_decision=decision.to_dict(), operation_trace=operation)
        self._record_operation_trace(operation)
        return result

    def write(
        self,
        request: MemoryWriteRequest | dict[str, Any] | None = None,
        *,
        records: list[MemoryRecord | dict[str, Any]] | None = None,
        mode: MemoryWriteMode | str = MemoryWriteMode.APPEND,
        actor: str | None = None,
        run_id: str | None = None,
        execution_identity: GraphExecutionIdentity | dict[str, Any] | None = None,
        standalone: bool = False,
        namespace: str | None = None,
        tenant_id: str | None = None,
        policy: MemoryPolicy | None = None,
    ) -> MemoryWriteResult:
        started = perf_counter()
        write_request = _coerce_write_request(
            request,
            records=records,
            mode=mode,
            actor=actor,
            run_id=run_id,
            execution_identity=execution_identity,
            standalone=standalone,
            namespace=namespace,
            tenant_id=tenant_id,
        )
        operation_type = _memory_write_operation(write_request.mode)
        operation = self._start_operation_trace(
            operation_type=operation_type,
            namespace=write_request.namespace,
            metadata={
                "accepted_count": len(write_request.records),
                "mode": write_request.mode.value,
                "memory_ids": [record.memory_id for record in write_request.records],
                "standalone": write_request.standalone,
                "execution_identity": (
                    write_request.execution_identity.to_dict()
                    if write_request.execution_identity is not None
                    else None
                ),
            },
        )
        decision = memory_policy_decision(
            f"memory.{operation_type}",
            namespace=write_request.namespace,
            tenant_id=write_request.tenant_id,
        )
        if not decision.allowed:
            operation = self._finish_write_trace(
                operation,
                started=started,
                policy_decision=decision.to_dict(),
                accepted_count=len(write_request.records),
                written_ids=[],
                skipped_count=len(write_request.records),
            )
            result = MemoryWriteResult(
                accepted_count=len(write_request.records),
                written_count=0,
                skipped_count=len(write_request.records),
                errors=[decision.reason],
                policy_decision=decision.to_dict(),
                operation_trace=operation,
            )
            self._record_operation_trace(operation)
            return result
        effective_policy = (
            self.policy
            if write_request.mode
            in {MemoryWriteMode.PROMOTE, MemoryWriteMode.INVALIDATE}
            else (policy or self.policy)
        )
        result = self.writer.write(
            write_request,
            store=self.store,
            policy=effective_policy,
        )
        operation = self._finish_write_trace(
            operation,
            started=started,
            policy_decision=decision.to_dict(),
            accepted_count=result.accepted_count,
            written_ids=result.memory_ids,
            skipped_count=result.skipped_count,
        )
        result = replace(result, policy_decision=decision.to_dict(), operation_trace=operation)
        self._record_operation_trace(operation)
        return result

    def get(self, memory_id: str) -> MemoryRecord | None:
        return self.store.get(memory_id)

    def forget(
        self,
        request: MemoryForgetRequest | dict[str, Any] | str,
    ) -> MemoryForgetResult:
        if isinstance(request, str):
            request = MemoryForgetRequest(memory_ids=[request])
        forget_request = _coerce_forget_request(request)
        started = perf_counter()
        operation = self._start_operation_trace(
            operation_type="forget",
            metadata={
                "memory_ids": list(forget_request.memory_ids),
                "filters": dict(forget_request.filters),
                "hard_delete": forget_request.hard_delete,
                "actor": forget_request.actor,
                "run_id": forget_request.run_id,
                "reason": forget_request.reason,
            },
        )
        decision = memory_policy_decision("memory.forget")
        if not decision.allowed:
            candidate_count = len(forget_request.memory_ids)
            operation = self._finish_forget_trace(
                operation,
                started=started,
                policy_decision=decision.to_dict(),
                forgotten_ids=[],
                candidate_count=candidate_count,
                skipped_count=candidate_count,
            )
            result = MemoryForgetResult(
                forgotten_count=0,
                skipped_count=candidate_count,
                warnings=[decision.reason],
                policy_decision=decision.to_dict(),
                operation_trace=operation,
            )
            self._record_operation_trace(operation)
            return result
        result = self.forgetting_engine.forget(
            forget_request,
            store=self.store,
            policy=self.policy,
        )
        operation = self._finish_forget_trace(
            operation,
            started=started,
            policy_decision=decision.to_dict(),
            forgotten_ids=result.memory_ids,
            candidate_count=result.forgotten_count + result.skipped_count,
            skipped_count=result.skipped_count,
        )
        result = replace(
            result,
            policy_decision=decision.to_dict(),
            operation_trace=operation,
        )
        self._record_operation_trace(operation)
        return result

    def consolidate(
        self,
        request: MemoryConsolidationRequest | dict[str, Any],
    ) -> MemoryConsolidationResult:
        consolidation_request = _coerce_consolidation_request(request)
        return self.consolidator.consolidate(
            consolidation_request,
            store=self.store,
            policy=self.policy,
            writer=self.writer,
        )

    def promote(
        self,
        memory_id: str,
        *,
        target_scope: MemoryScope | str | None = None,
        target_kind: MemoryKind | str | None = None,
        reason: str | None = None,
        policy: MemoryPolicy | None = None,
    ) -> MemoryWriteResult:
        del policy  # mutation authorization is owned by this runtime instance
        target_scope = (
            None if target_scope is None else MemoryScope.from_value(target_scope)
        )
        target_kind = (
            None if target_kind is None else MemoryKind.from_value(target_kind)
        )
        record = self.store.get(memory_id)
        return self._run_memory_write_mutation(
            operation_type="promote",
            accepted_count=1,
            namespace=None if record is None else record.namespace,
            tenant_id=None if record is None else record.tenant_id,
            metadata={
                "memory_ids": [memory_id],
                "target_scope": None if target_scope is None else target_scope.value,
                "target_kind": None if target_kind is None else target_kind.value,
                "reason": reason,
            },
            invoke=lambda runtime_policy: self.promotion_engine.promote(
                memory_id,
                store=self.store,
                target_scope=target_scope,
                target_kind=target_kind,
                reason=reason,
                policy=runtime_policy,
            ),
        )

    def invalidate(
        self,
        memory_id: str,
        *,
        reason: str,
        policy: MemoryPolicy | None = None,
    ) -> MemoryWriteResult:
        del policy  # mutation authorization is owned by this runtime instance
        record = self.store.get(memory_id)
        return self._run_memory_write_mutation(
            operation_type="invalidate",
            accepted_count=1,
            namespace=None if record is None else record.namespace,
            tenant_id=None if record is None else record.tenant_id,
            metadata={"memory_ids": [memory_id], "reason": reason},
            invoke=lambda runtime_policy: self.invalidation_engine.invalidate(
                memory_id,
                store=self.store,
                reason=reason,
                policy=runtime_policy,
            ),
        )

    def invalidate_many(
        self,
        memory_ids: list[str],
        *,
        reason: str,
        policy: MemoryPolicy | None = None,
    ) -> MemoryWriteResult:
        del policy  # mutation authorization is owned by this runtime instance
        normalized_ids = list(memory_ids)
        return self._run_memory_write_mutation(
            operation_type="invalidate",
            accepted_count=len(normalized_ids),
            metadata={"memory_ids": normalized_ids, "reason": reason},
            invoke=lambda runtime_policy: self.invalidation_engine.invalidate_many(
                normalized_ids,
                store=self.store,
                reason=reason,
                policy=runtime_policy,
            ),
        )

    def lifecycle(self) -> dict[str, Any]:
        return self.lifecycle_manager.run(store=self.store, policy=self.policy)

    def _run_memory_write_mutation(
        self,
        *,
        operation_type: str,
        accepted_count: int,
        metadata: dict[str, Any],
        invoke: Callable[[MemoryPolicy], MemoryWriteResult],
        namespace: str | None = None,
        tenant_id: str | None = None,
    ) -> MemoryWriteResult:
        started = perf_counter()
        operation = self._start_operation_trace(
            operation_type=operation_type,
            namespace=namespace,
            metadata=metadata,
        )
        decision = memory_policy_decision(
            f"memory.{operation_type}",
            namespace=namespace,
            tenant_id=tenant_id,
        )
        if not decision.allowed:
            operation = self._finish_write_trace(
                operation,
                started=started,
                policy_decision=decision.to_dict(),
                accepted_count=accepted_count,
                written_ids=[],
                skipped_count=accepted_count,
            )
            result = MemoryWriteResult(
                accepted_count=accepted_count,
                skipped_count=accepted_count,
                errors=[decision.reason],
                policy_decision=decision.to_dict(),
                operation_trace=operation,
            )
            self._record_operation_trace(operation)
            return result

        result = invoke(self.policy)
        operation = self._finish_write_trace(
            operation,
            started=started,
            policy_decision=decision.to_dict(),
            accepted_count=result.accepted_count,
            written_ids=result.memory_ids,
            skipped_count=result.skipped_count,
        )
        result = replace(
            result,
            policy_decision=decision.to_dict(),
            operation_trace=operation,
        )
        self._record_operation_trace(operation)
        return result

    def _start_operation_trace(
        self,
        *,
        operation_type: str,
        namespace: str | None = None,
        query: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryOperationTrace:
        operation_id = uuid4().hex
        context = self._operation_trace_context(operation_id)
        return MemoryOperationTrace(
            operation_id=operation_id,
            operation_type=operation_type,
            namespace=namespace,
            query=query,
            trace_id=context.trace_id if context is not None else None,
            span_id=context.span_id if context is not None else None,
            metadata=dict(metadata or {}),
        )

    def _finish_recall_trace(
        self,
        operation: MemoryOperationTrace,
        *,
        started: float,
        policy_decision: dict[str, Any],
        results: list[Any],
        candidate_count: int,
        filtered_count: int,
    ) -> MemoryOperationTrace:
        return MemoryOperationTrace(
            operation_id=operation.operation_id,
            operation_type=operation.operation_type,
            namespace=operation.namespace,
            query=operation.query,
            policy_decision=policy_decision,
            candidate_count=candidate_count,
            selected_count=len(results),
            filtered_count=filtered_count,
            scores=_score_trace(results),
            duration_ms=round((perf_counter() - started) * 1000, 3),
            trace_id=operation.trace_id,
            span_id=operation.span_id,
            metadata={
                **operation.metadata,
                "selected_memory_ids": [getattr(result, "memory_id", "") for result in results],
            },
        )

    def _finish_write_trace(
        self,
        operation: MemoryOperationTrace,
        *,
        started: float,
        policy_decision: dict[str, Any],
        accepted_count: int,
        written_ids: list[str],
        skipped_count: int,
    ) -> MemoryOperationTrace:
        return MemoryOperationTrace(
            operation_id=operation.operation_id,
            operation_type=operation.operation_type,
            namespace=operation.namespace,
            query=operation.query,
            policy_decision=policy_decision,
            candidate_count=accepted_count,
            selected_count=len(written_ids),
            filtered_count=skipped_count,
            scores=[],
            duration_ms=round((perf_counter() - started) * 1000, 3),
            trace_id=operation.trace_id,
            span_id=operation.span_id,
            metadata={**operation.metadata, "written_ids": list(written_ids)},
        )

    def _finish_forget_trace(
        self,
        operation: MemoryOperationTrace,
        *,
        started: float,
        policy_decision: dict[str, Any],
        forgotten_ids: list[str],
        candidate_count: int,
        skipped_count: int,
    ) -> MemoryOperationTrace:
        return MemoryOperationTrace(
            operation_id=operation.operation_id,
            operation_type=operation.operation_type,
            namespace=operation.namespace,
            query=operation.query,
            policy_decision=policy_decision,
            candidate_count=candidate_count,
            selected_count=len(forgotten_ids),
            filtered_count=skipped_count,
            scores=[],
            duration_ms=round((perf_counter() - started) * 1000, 3),
            trace_id=operation.trace_id,
            span_id=operation.span_id,
            metadata={
                **operation.metadata,
                "forgotten_ids": list(forgotten_ids),
            },
        )

    def _operation_trace_context(self, operation_id: str) -> TraceContext | None:
        if self.trace_context is None:
            return None
        return self.trace_context.child(
            memory_operation_id=operation_id,
        )

    def _record_operation_trace(self, operation: MemoryOperationTrace) -> None:
        if self.trace_recorder is None:
            return
        context = (
            self.trace_context.child(
                span_id=operation.span_id,
                memory_operation_id=operation.operation_id,
            )
            if self.trace_context is not None and operation.span_id is not None
            else None
        )
        self.trace_recorder.record(
            MemoryTraceEvent(
                event_type="memory_operation",
                payload=operation.to_dict(),
                trace_context=context,
            )
        )


def _coerce_query(value: MemoryQuery | dict[str, Any] | str) -> MemoryQuery:
    if isinstance(value, MemoryQuery):
        return value
    if isinstance(value, dict):
        return MemoryQuery.from_dict(value)
    return MemoryQuery(query=str(value))


def _memory_write_operation(mode: MemoryWriteMode) -> str:
    if mode is MemoryWriteMode.PROMOTE:
        return "promote"
    if mode is MemoryWriteMode.INVALIDATE:
        return "invalidate"
    return "write"


def memory_policy_decision(
    policy_id: str,
    *,
    namespace: str | None = None,
    tenant_id: str | None = None,
) -> PolicyDecision:
    for label, value in {"namespace": namespace, "tenant_id": tenant_id}.items():
        if value is None:
            continue
        text = str(value)
        if ".." in text or text.startswith("/") or text.startswith("\\"):
            return PolicyDecision.block(
                policy_id,
                reason=f"invalid memory {label}: {text}",
                risk_level="high",
                metadata={label: text},
            )
    return PolicyDecision.allow(policy_id, reason="memory policy allowed")


def _recall_candidate_count(result: MemoryRecallResult) -> int:
    diagnostics = dict(result.diagnostics)
    requested = diagnostics.get("requested_count")
    if requested is not None:
        try:
            return int(requested)
        except (TypeError, ValueError):
            pass
    return len(result.results)


def _recall_filtered_count(result: MemoryRecallResult) -> int:
    candidate_count = _recall_candidate_count(result)
    return max(0, candidate_count - len(result.results))


def _score_trace(results: list[Any]) -> list[dict[str, Any]]:
    scores: list[dict[str, Any]] = []
    for result in results:
        scores.append(
            {
                "memory_id": str(getattr(result, "memory_id", "")),
                "score": float(getattr(result, "score", 0.0) or 0.0),
                "source": str(getattr(result, "source", "memory")),
                "match_reasons": [
                    str(item) for item in getattr(result, "match_reasons", []) or []
                ],
            }
        )
    return scores


def _memory_error_envelope(
    error_type: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "error_code": error_type,
        "error_type": error_type,
        "message": message,
        "domain": "memory",
        "severity": "error",
        "retryable": False,
        "details": dict(details or {}),
    }


def _coerce_write_request(
    request: MemoryWriteRequest | dict[str, Any] | None,
    *,
    records: list[MemoryRecord | dict[str, Any]] | None,
    mode: MemoryWriteMode | str,
    actor: str | None,
    run_id: str | None,
    execution_identity: GraphExecutionIdentity | dict[str, Any] | None,
    standalone: bool,
    namespace: str | None,
    tenant_id: str | None,
) -> MemoryWriteRequest:
    if isinstance(request, MemoryWriteRequest):
        return request
    if isinstance(request, dict):
        return MemoryWriteRequest.from_dict(request)
    return MemoryWriteRequest(
        records=[coerce_memory_record(record) for record in (records or [])],
        mode=MemoryWriteMode.from_value(mode),
        actor=actor,
        run_id=run_id,
        execution_identity=execution_identity,
        standalone=standalone,
        namespace=namespace,
        tenant_id=tenant_id,
    )


def _coerce_forget_request(
    request: MemoryForgetRequest | dict[str, Any],
) -> MemoryForgetRequest:
    if isinstance(request, MemoryForgetRequest):
        return request
    return MemoryForgetRequest.from_dict(request)


def _coerce_consolidation_request(
    request: MemoryConsolidationRequest | dict[str, Any],
) -> MemoryConsolidationRequest:
    if isinstance(request, MemoryConsolidationRequest):
        return request
    return MemoryConsolidationRequest.from_dict(request)
