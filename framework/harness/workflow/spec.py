from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.side_effects.models import HarnessTerminalSideEffectPolicy
from framework.harness.workflow.canonical import required_text
from framework.harness.workflow.dsl import HarnessGraphSpec
from framework.harness.workflow.step import HarnessStepSpec
from framework.harness.workflow.versioning import HARNESS_GRAPH_DSL_SCHEMA, LEGACY_WORKFLOW_SCHEMA
from framework.shared.json import to_jsonable


class HarnessRouteKind(StrEnum):
    ALWAYS = "always"
    ON_VERDICT = "on_verdict"
    ON_STATUS = "on_status"


@dataclass(frozen=True)
class HarnessRoutingRule:
    from_step: str
    to_step: str
    kind: HarnessRouteKind | str = HarnessRouteKind.ALWAYS
    condition: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.from_step).strip():
            raise HarnessValidationError("from_step is required")
        if not str(self.to_step).strip():
            raise HarnessValidationError("to_step is required")
        object.__setattr__(self, "from_step", str(self.from_step))
        object.__setattr__(self, "to_step", str(self.to_step))
        object.__setattr__(self, "kind", HarnessRouteKind(self.kind))
        object.__setattr__(self, "condition", dict(self.condition))

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_step": self.from_step,
            "to_step": self.to_step,
            "kind": self.kind.value,
            "condition": to_jsonable(self.condition),
        }


@dataclass(frozen=True)
class HarnessWorkflowSpec:
    workflow_id: str
    steps: tuple[HarnessStepSpec, ...]
    entry_step_id: str
    terminal_policies: dict[str, Any] = field(default_factory=dict)
    routing_rules: tuple[HarnessRoutingRule, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    terminal_side_effect_policy: HarnessTerminalSideEffectPolicy | dict[str, Any] | None = None
    workflow_version: str | None = None
    graph: HarnessGraphSpec | dict[str, Any] | None = None

    def __post_init__(self) -> None:
        workflow_id = str(self.workflow_id).strip()
        entry_step_id = str(self.entry_step_id).strip()
        if not workflow_id:
            raise HarnessValidationError("workflow_id is required")
        if not entry_step_id:
            raise HarnessValidationError("entry_step_id is required")
        if not self.steps:
            raise HarnessValidationError("workflow must contain at least one step")
        if not all(isinstance(step, HarnessStepSpec) for step in self.steps):
            raise HarnessValidationError("steps must be HarnessStepSpec values")
        step_ids = [step.step_id for step in self.steps]
        duplicate_ids = sorted({step_id for step_id in step_ids if step_ids.count(step_id) > 1})
        if duplicate_ids:
            raise HarnessValidationError("step_id values must be unique", details={"duplicates": duplicate_ids})
        if entry_step_id not in step_ids:
            raise HarnessValidationError("entry_step_id must reference a declared step")
        for rule in self.routing_rules:
            if rule.from_step not in step_ids or rule.to_step not in step_ids:
                raise HarnessValidationError("routing rules must reference declared steps")
        graph = self.graph
        if graph is not None and not isinstance(graph, HarnessGraphSpec):
            if not isinstance(graph, dict):
                raise HarnessValidationError("graph must be HarnessGraphSpec")
            graph = HarnessGraphSpec.from_dict(graph)
        if graph is not None and self.routing_rules:
            raise HarnessValidationError(
                "workflow cannot activate explicit graph and legacy routing rules together",
                code="ambiguous_workflow_declaration",
                details={"workflow_id": workflow_id},
            )
        terminal_policies = dict(self.terminal_policies)
        embedded_policy = terminal_policies.get("side_effect")
        explicit_policy = self.terminal_side_effect_policy
        if explicit_policy is not None and not isinstance(
            explicit_policy,
            HarnessTerminalSideEffectPolicy,
        ):
            explicit_policy = HarnessTerminalSideEffectPolicy.from_dict(explicit_policy)
        if embedded_policy is not None:
            if isinstance(embedded_policy, HarnessTerminalSideEffectPolicy):
                parsed_embedded = embedded_policy
            elif isinstance(embedded_policy, dict):
                parsed_embedded = HarnessTerminalSideEffectPolicy.from_dict(embedded_policy)
            else:
                raise HarnessValidationError("terminal side-effect policy must be an object")
            if explicit_policy is not None and explicit_policy != parsed_embedded:
                raise HarnessValidationError("terminal side-effect policy declarations conflict")
            explicit_policy = parsed_embedded
        if explicit_policy is not None:
            terminal_policies["side_effect"] = explicit_policy.to_dict()
        metadata = dict(self.metadata)
        workflow_version = required_text(
            self.workflow_version or metadata.get("version", "1"),
            "workflow_version",
        )
        object.__setattr__(self, "workflow_id", workflow_id)
        object.__setattr__(self, "entry_step_id", entry_step_id)
        object.__setattr__(self, "terminal_policies", terminal_policies)
        object.__setattr__(self, "terminal_side_effect_policy", explicit_policy)
        object.__setattr__(self, "workflow_version", workflow_version)
        object.__setattr__(self, "graph", graph)
        object.__setattr__(self, "metadata", metadata)

    @property
    def step_ids(self) -> tuple[str, ...]:
        return tuple(step.step_id for step in self.steps)

    @property
    def declaration_mode(self) -> str:
        return "graph" if self.graph is not None else "legacy"

    @property
    def schema_version(self) -> str:
        return HARNESS_GRAPH_DSL_SCHEMA if self.graph is not None else LEGACY_WORKFLOW_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "workflow_id": self.workflow_id,
            "steps": [step.to_dict() for step in self.steps],
            "entry_step_id": self.entry_step_id,
            "terminal_policies": to_jsonable(self.terminal_policies),
            "routing_rules": [rule.to_dict() for rule in self.routing_rules],
            "metadata": to_jsonable(self.metadata),
        }
        if self.graph is not None:
            payload.update(
                {
                    "schema_version": self.schema_version,
                    "workflow_version": self.workflow_version,
                    "graph": self.graph.to_dict(),
                }
            )
        return payload


__all__ = ["HarnessRouteKind", "HarnessRoutingRule", "HarnessWorkflowSpec"]
