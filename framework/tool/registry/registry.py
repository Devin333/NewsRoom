from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from framework.tool.models import ToolDefinition, ToolExecutorFn, ToolPolicy
from framework.tool.runtime.errors import ToolDefinitionError


DuplicateToolPolicy = Literal["error", "skip", "replace_explicit", "replace"]
_DUPLICATE_POLICIES = {"error", "skip", "replace_explicit", "replace"}


@dataclass(frozen=True)
class RegisteredTool:
    definition: ToolDefinition
    executor: ToolExecutorFn


@dataclass(frozen=True)
class ToolRegistryValidationResult:
    ok: bool
    errors: tuple[str, ...]
    tool_count: int

    @property
    def valid(self) -> bool:
        return self.ok

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": list(self.errors),
            "tool_count": self.tool_count,
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(
        self,
        definition: ToolDefinition,
        executor: ToolExecutorFn,
        *,
        duplicate_policy: DuplicateToolPolicy = "error",
    ) -> RegisteredTool:
        if duplicate_policy not in _DUPLICATE_POLICIES:
            raise ToolDefinitionError(f"unsupported duplicate policy: {duplicate_policy}")

        existing = self._tools.get(definition.name)
        if existing is not None and duplicate_policy == "error":
            raise ToolDefinitionError(
                "tool already registered: "
                f"{definition.name} "
                f"(old namespace={existing.definition.namespace}, "
                f"new namespace={definition.namespace})"
            )
        if existing is not None and duplicate_policy == "skip":
            return existing

        registered = RegisteredTool(definition=definition, executor=executor)
        self._tools[definition.name] = registered
        return registered

    def unregister(self, tool_name: str) -> None:
        self.remove(tool_name)

    def remove(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> RegisteredTool:
        return self.require(name)

    def require(self, name: str) -> RegisteredTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolDefinitionError(f"tool is not registered: {name}") from exc

    def maybe_get(self, name: str) -> RegisteredTool | None:
        return self._tools.get(name)

    def find(self, name: str) -> RegisteredTool | None:
        return self.maybe_get(name)

    def list(self, namespace: str | None = None) -> list[RegisteredTool]:
        registered = list(self._tools.values())
        if namespace is not None:
            registered = [
                item for item in registered if item.definition.namespace == namespace
            ]
        return registered

    def list_tools(self) -> list[ToolDefinition]:
        return [registered.definition for registered in self._tools.values()]

    def list_registered_tools(self) -> list[RegisteredTool]:
        return list(self._tools.values())

    def list_tools_for_agent(self, agent_id: str, policy: ToolPolicy) -> list[ToolDefinition]:
        _ = agent_id
        return [definition for definition in self.list_tools() if policy.exposes(definition)]

    def validate(self) -> ToolRegistryValidationResult:
        return self.validate_no_conflicts()

    def validate_no_conflicts(self) -> ToolRegistryValidationResult:
        errors: list[str] = []
        seen_tool_ids: dict[str, str] = {}
        for registered_name, registered in self._tools.items():
            definition = registered.definition
            if registered_name != definition.name:
                errors.append(
                    "registered key "
                    f"{registered_name} does not match definition name {definition.name}"
                )
            if not definition.namespace or not definition.name.startswith(
                f"{definition.namespace}."
            ):
                errors.append(f"tool namespace is inconsistent for {definition.name}")
            if not definition.version:
                errors.append(f"tool version is missing for {definition.name}")
            if not definition.tool_id:
                errors.append(f"tool id is missing for {definition.name}")
            existing_name = seen_tool_ids.get(definition.tool_id)
            if existing_name is not None and existing_name != definition.name:
                errors.append(
                    f"tool id {definition.tool_id} is shared by "
                    f"{existing_name} and {definition.name}"
                )
            seen_tool_ids[definition.tool_id] = definition.name
            if not callable(registered.executor):
                errors.append(f"tool executor is not callable for {definition.name}")
        return ToolRegistryValidationResult(
            ok=not errors,
            errors=tuple(errors),
            tool_count=len(self._tools),
        )

    def describe(self) -> list[dict[str, Any]]:
        return [definition.to_dict() for definition in self.list_tools()]

    def export_schema_for_llm(
        self,
        agent_id: str | list[str] = "",
        policy: ToolPolicy | None = None,
    ) -> list[dict[str, Any]]:
        if isinstance(agent_id, list):
            policy = ToolPolicy(allowed_tools=list(agent_id), require_explicit_allowlist=True)
            agent_id = ""

        definitions = self.list_tools()
        if policy is not None:
            definitions = self.list_tools_for_agent(agent_id, policy)
        return [definition.to_dict() for definition in definitions]
