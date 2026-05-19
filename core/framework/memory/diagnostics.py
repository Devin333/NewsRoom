from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MemoryRuntimeDiagnostics:
    store_type: str
    recall_strategy_type: str
    assembler_type: str
    writer_type: str
    policy: dict[str, Any]
    operations: dict[str, bool]
    warnings: list[str] = field(default_factory=list)

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


def inspect_memory_runtime(runtime) -> MemoryRuntimeDiagnostics:
    policy = runtime.policy
    return MemoryRuntimeDiagnostics(
        store_type=type(runtime.store).__name__,
        recall_strategy_type=type(runtime.recall_strategy).__name__,
        assembler_type=type(runtime.assembler).__name__,
        writer_type=type(runtime.writer).__name__,
        policy={
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
        },
        operations={
            "recall": policy.allow_recall,
            "write": policy.allow_write,
            "consolidate": policy.allow_write,
            "forget": True,
            "direct_delete": True,
        },
    )
