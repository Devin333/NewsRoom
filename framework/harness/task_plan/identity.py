from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.task_plan.canonical import (
    canonical_payload_checksum,
    identifier,
)
from framework.harness.task_plan.schema import (
    DEFAULT_TASK_PLAN_SCHEMA_REGISTRY,
    GRAPH_ONLY_TASK_PLAN_STAGE_BINDING_SCHEMA,
    GRAPH_ONLY_TASK_PLAN_STAGE_IDENTITY_SCHEMA,
    TaskPlanContractKind,
)
from framework.harness.task_plan.stage_binding import TaskPlanStageBinding


@dataclass(frozen=True, slots=True)
class TaskPlanStageIdentity:
    """Exact run and frozen-Graph identity for one dynamic TaskPlan stage."""

    run_id: str
    stage_binding: TaskPlanStageBinding = field(repr=False)
    schema_version: str | None = None
    graph_schema_version: str = field(init=False)
    compiler_version: str = field(init=False)
    condition_policy_version: str = field(init=False)
    graph_id: str = field(init=False)
    graph_version: str = field(init=False)
    graph_checksum: str = field(init=False)
    stage_id: str = field(init=False)
    stage_binding_checksum: str = field(init=False)
    identity_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        run_id = identifier(self.run_id, "run_id")
        if not isinstance(self.stage_binding, TaskPlanStageBinding):
            raise TypeError("stage_binding must be TaskPlanStageBinding")
        if self.stage_binding.schema_version != GRAPH_ONLY_TASK_PLAN_STAGE_BINDING_SCHEMA:
            raise HarnessValidationError(
                "TaskPlan stage identity requires the live Graph v2 binding schema",
                code="legacy_task_plan_binding_schema_forbidden",
                details={"schema_version": self.stage_binding.schema_version},
            )
        expected_schema = GRAPH_ONLY_TASK_PLAN_STAGE_IDENTITY_SCHEMA
        schema_version = (
            expected_schema if self.schema_version is None else self.schema_version
        )
        DEFAULT_TASK_PLAN_SCHEMA_REGISTRY.require_executable(
            TaskPlanContractKind.STAGE_IDENTITY,
            schema_version,
        )
        if schema_version != expected_schema:
            raise HarnessValidationError(
                "TaskPlan stage identity schema does not match its frozen Graph binding",
                code="task_plan_stage_identity_schema_mismatch",
                details={
                    "schema_version": schema_version,
                    "expected_schema_version": expected_schema,
                },
            )
        graph = self.stage_binding.graph
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "graph_schema_version", graph.schema_version)
        object.__setattr__(self, "compiler_version", graph.compiler_version)
        object.__setattr__(
            self,
            "condition_policy_version",
            graph.condition_policy_version,
        )
        object.__setattr__(self, "graph_id", self.stage_binding.graph_id)
        object.__setattr__(self, "graph_version", self.stage_binding.graph_version)
        object.__setattr__(self, "graph_checksum", self.stage_binding.graph_checksum)
        object.__setattr__(self, "stage_id", self.stage_binding.stage_id)
        object.__setattr__(
            self,
            "stage_binding_checksum",
            self.stage_binding.binding_checksum,
        )
        object.__setattr__(
            self,
            "identity_checksum",
            canonical_payload_checksum(self.checksum_projection()),
        )

    @property
    def is_graph_only(self) -> bool:
        return self.schema_version == GRAPH_ONLY_TASK_PLAN_STAGE_IDENTITY_SCHEMA

    @property
    def graph_ref(self) -> str:
        reference = self.stage_binding.graph.graph_ref
        assert reference is not None
        return reference.exact_ref

    def checksum_projection(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "graph_schema_version": self.graph_schema_version,
            "compiler_version": self.compiler_version,
            "condition_policy_version": self.condition_policy_version,
            "graph_id": self.graph_id,
            "graph_version": self.graph_version,
            "graph_checksum": self.graph_checksum,
            "stage_id": self.stage_id,
            "stage_binding_checksum": self.stage_binding_checksum,
        }
        payload["graph_ref"] = self.graph_ref
        return payload

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.checksum_projection(),
            "identity_checksum": self.identity_checksum,
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        stage_binding: TaskPlanStageBinding,
    ) -> "TaskPlanStageIdentity":
        if not isinstance(value, Mapping):
            raise HarnessValidationError(
                "TaskPlan stage identity must be an object",
                code="task_plan_stage_identity_projection_invalid",
            )
        run_id = value.get("run_id")
        schema_version = value.get("schema_version")
        if not isinstance(run_id, str) or not isinstance(schema_version, str):
            raise HarnessValidationError(
                "TaskPlan stage identity fields are invalid",
                code="task_plan_stage_identity_projection_invalid",
            )
        restored = cls(
            run_id=run_id,
            stage_binding=stage_binding,
            schema_version=schema_version,
        )
        expected = restored.to_dict()
        if set(value) != set(expected):
            raise HarnessValidationError(
                "TaskPlan stage identity fields do not match its schema",
                code="task_plan_stage_identity_projection_invalid",
                details={
                    "missing": sorted(set(expected).difference(value)),
                    "unexpected": sorted(
                        str(item) for item in set(value).difference(expected)
                    ),
                },
            )
        if dict(value) != expected:
            raise HarnessValidationError(
                "TaskPlan stage identity does not match its frozen Graph binding",
                code="task_plan_stage_identity_checksum_invalid",
            )
        return restored


__all__ = ["TaskPlanStageIdentity"]
