from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from framework.memory.diagnostics.health import MemoryHealthReport, MemoryHealthStatus
from framework.memory.diagnostics.metrics import MemoryRuntimeMetrics


@dataclass(frozen=True)
class MemoryRuntimeDiagnostics:
    store_type: str
    recall_strategy_type: str
    assembler_type: str
    writer_type: str
    policy: dict[str, Any]
    operations: dict[str, bool]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "store_type": self.store_type,
            "recall_strategy_type": self.recall_strategy_type,
            "assembler_type": self.assembler_type,
            "writer_type": self.writer_type,
            "policy": dict(self.policy),
            "operations": dict(self.operations),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class MemoryRuntimeInspection:
    store_type: str
    policy: dict[str, Any]
    metrics: MemoryRuntimeMetrics
    health: MemoryHealthReport

    def to_dict(self) -> dict[str, Any]:
        return {
            "store_type": self.store_type,
            "policy": dict(self.policy),
            "metrics": self.metrics.to_dict(),
            "health": self.health.to_dict(),
        }


class MemoryRuntimeInspector:
    def inspect(self, runtime) -> MemoryRuntimeInspection:
        return MemoryRuntimeInspection(
            store_type=type(runtime.store).__name__,
            policy=_policy_payload(runtime.policy),
            metrics=_metrics(runtime.store),
            health=MemoryHealthReport(status=MemoryHealthStatus.HEALTHY, checks={"store": True}),
        )


def inspect_memory_runtime(runtime) -> MemoryRuntimeDiagnostics:
    policy = runtime.policy
    return MemoryRuntimeDiagnostics(
        store_type=type(runtime.store).__name__,
        recall_strategy_type=type(runtime.recall_strategy).__name__,
        assembler_type=type(runtime.assembler).__name__,
        writer_type=type(runtime.writer).__name__,
        policy=_policy_payload(policy),
        operations={
            "recall": policy.allow_recall,
            "write": policy.allow_write,
            "consolidate": policy.allow_write,
            "forget": True,
            "direct_delete": True,
        },
        warnings=[],
    )


def _policy_payload(policy) -> dict[str, Any]:
    return {
        "allow_write": policy.allow_write,
        "allow_recall": policy.allow_recall,
        "require_refs": policy.require_refs,
        "min_confidence_to_write": policy.min_confidence_to_write,
        "min_confidence_to_recall": policy.min_confidence_to_recall,
        "max_recall_results": policy.max_recall_results,
        "max_context_tokens": policy.max_context_tokens,
        "allow_global_write": policy.allow_global_write,
        "allowed_scopes": [scope.value for scope in policy.allowed_scopes],
        "allowed_kinds": [kind.value for kind in policy.allowed_kinds],
    }


def _metrics(store) -> MemoryRuntimeMetrics:
    records = store.records() if callable(getattr(store, "records", None)) else []
    by_kind: dict[str, int] = {}
    by_scope: dict[str, int] = {}
    confidences: list[float] = []
    for record in records:
        by_kind[record.kind.value] = by_kind.get(record.kind.value, 0) + 1
        by_scope[record.scope.value] = by_scope.get(record.scope.value, 0) + 1
        if record.confidence is not None:
            confidences.append(record.confidence)
    return MemoryRuntimeMetrics(
        total_records=len(records),
        records_by_kind=by_kind,
        records_by_scope=by_scope,
        expired_records=sum(1 for record in records if record.is_expired()),
        invalidated_records=sum(1 for record in records if record.is_invalidated()),
        average_confidence=sum(confidences) / len(confidences) if confidences else None,
    )
