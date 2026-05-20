from __future__ import annotations

from typing import Any, cast

from framework.memory.models import MemoryConsolidationRequest, MemoryForgetRequest, MemoryQuery, MemoryRecord
from framework.memory.runtime import MemoryRuntime
from framework.tool import ToolDefinition


class MemoryToolAdapter:
    def register(self, registry: Any, *, runtime: MemoryRuntime) -> None:
        self._register_tool(registry, "memory.recall", lambda args: self.recall_tool(args, runtime=runtime))
        self._register_tool(registry, "memory.write", lambda args: self.write_tool(args, runtime=runtime))
        self._register_tool(registry, "memory.forget", lambda args: self.forget_tool(args, runtime=runtime))
        self._register_tool(registry, "memory.consolidate", lambda args: self.consolidate_tool(args, runtime=runtime))
        self._register_tool(registry, "memory.explain", lambda args: self.explain_tool(args, runtime=runtime))

    def recall_tool(self, args: dict[str, Any], *, runtime: MemoryRuntime) -> dict[str, Any]:
        return runtime.recall(MemoryQuery.from_dict(args)).to_dict()

    def write_tool(self, args: dict[str, Any], *, runtime: MemoryRuntime) -> dict[str, Any]:
        records = [MemoryRecord.from_dict(item) for item in args.get("records") or []]
        return runtime.write(records=cast(Any, records), actor=args.get("actor"), run_id=args.get("run_id")).to_dict()

    def forget_tool(self, args: dict[str, Any], *, runtime: MemoryRuntime) -> dict[str, Any]:
        return runtime.forget(MemoryForgetRequest.from_dict(args)).to_dict()

    def consolidate_tool(self, args: dict[str, Any], *, runtime: MemoryRuntime) -> dict[str, Any]:
        return runtime.consolidate(MemoryConsolidationRequest.from_dict(args)).to_dict()

    def explain_tool(self, args: dict[str, Any], *, runtime: MemoryRuntime) -> dict[str, Any]:
        return {"store_type": type(runtime.store).__name__, "policy": type(runtime.policy).__name__}

    def _register_tool(self, registry: Any, name: str, executor: Any) -> None:
        try:
            registry.register(
                ToolDefinition(
                    name=name,
                    description=f"Memory runtime {name.split('.')[-1]} operation.",
                    input_schema={"type": "object"},
                    side_effect="write" if name != "memory.recall" and name != "memory.explain" else "none",
                    metadata={"framework_memory": True},
                ),
                executor,
                duplicate_policy="replace",
            )
        except TypeError:
            registry.register(name, executor)
