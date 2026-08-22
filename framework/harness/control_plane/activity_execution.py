from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_runtime import (
    HarnessGraphActivity,
    HarnessGraphActivityResult,
)
from framework.harness.control_plane.node_output import HarnessNodeOutputCommit
from framework.harness.graph.activity import (
    HarnessLeafActivityKind,
    graph_activity_input_checksum,
)
from framework.harness.graph.bindings import HarnessActivityUsage
from framework.harness.graph.canonical import (
    canonical_checksum,
    freeze_json,
    mapping_to_dict,
    required_text,
)
from framework.harness.workers.result import HarnessWorkerResult


HARNESS_GRAPH_ACTIVITY_EXECUTION_INPUT_SCHEMA = (
    "newsroom.harness-graph-activity-execution-input/v2"
)
HARNESS_GRAPH_ACTIVITY_TASK_CONTEXT_SCHEMA = (
    "newsroom.harness-graph-activity-task-context/v1"
)
HARNESS_GRAPH_ACTIVITY_FAILURE_EVIDENCE_SCHEMA = (
    "newsroom.harness-graph-activity-failure-evidence/v1"
)
HARNESS_GRAPH_ACTIVITY_TASK_CONTEXT_KEY = "harness_graph_activity"

_RESERVED_TASK_KEYS = frozenset(
    {HARNESS_GRAPH_ACTIVITY_TASK_CONTEXT_KEY, "harness_activity"}
)


@dataclass(frozen=True, slots=True)
class HarnessGraphActivityExecutionInput:
    """Checksum-bound input the control plane admits for one Graph activity."""

    activity_id: str
    activity_checksum: str
    task: Mapping[str, Any]
    leaf_activity_kind: HarnessLeafActivityKind | str
    required_usage: HarnessActivityUsage | str
    graph_checkpoint_ref: str
    output_keys: tuple[str, ...]
    timeout_seconds: float | None = None
    schema_version: str = HARNESS_GRAPH_ACTIVITY_EXECUTION_INPUT_SCHEMA
    input_ref: str = field(init=False)
    binding_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "activity_id",
            required_text(self.activity_id, "activity_execution_input.activity_id"),
        )
        object.__setattr__(
            self,
            "activity_checksum",
            _checksum(self.activity_checksum, "activity_execution_input.activity_checksum"),
        )
        if not isinstance(self.task, Mapping):
            raise HarnessValidationError(
                "Graph activity execution task must be an object",
                code="graph_activity_execution_input_invalid",
            )
        task = freeze_json(dict(self.task), "$.graph_activity_execution_input.task")
        if not isinstance(task, Mapping):  # pragma: no cover - guarded above
            raise AssertionError("canonical Graph activity task must remain a mapping")
        reserved = sorted(set(task).intersection(_RESERVED_TASK_KEYS))
        if reserved:
            raise HarnessValidationError(
                "Graph activity task cannot supply Harness-owned activity context",
                code="graph_activity_task_context_reserved",
                details={"keys": reserved},
            )
        object.__setattr__(self, "task", task)
        try:
            leaf_kind = HarnessLeafActivityKind(self.leaf_activity_kind)
            required_usage = HarnessActivityUsage(self.required_usage)
        except (TypeError, ValueError) as exc:
            raise HarnessValidationError(
                "Graph activity execution binding is unsupported",
                code="graph_activity_execution_binding_invalid",
            ) from exc
        object.__setattr__(self, "leaf_activity_kind", leaf_kind)
        object.__setattr__(self, "required_usage", required_usage)
        object.__setattr__(
            self,
            "graph_checkpoint_ref",
            required_text(
                self.graph_checkpoint_ref,
                "activity_execution_input.graph_checkpoint_ref",
            ),
        )
        object.__setattr__(self, "output_keys", _output_keys(self.output_keys))
        timeout_seconds = self.timeout_seconds
        if timeout_seconds is not None:
            if (
                isinstance(timeout_seconds, bool)
                or not isinstance(timeout_seconds, int | float)
                or not math.isfinite(float(timeout_seconds))
                or float(timeout_seconds) <= 0
            ):
                raise HarnessValidationError(
                    "Graph activity timeout must be finite and positive",
                    code="graph_activity_execution_timeout_invalid",
                )
            object.__setattr__(self, "timeout_seconds", float(timeout_seconds))
        if self.schema_version != HARNESS_GRAPH_ACTIVITY_EXECUTION_INPUT_SCHEMA:
            raise HarnessValidationError(
                "unsupported Graph activity execution input schema",
                code="unsupported_graph_activity_execution_input_schema",
            )
        input_ref = graph_activity_input_checksum(mapping_to_dict(task))
        object.__setattr__(self, "input_ref", input_ref)
        object.__setattr__(
            self,
            "binding_checksum",
            canonical_checksum(self.checksum_projection()),
        )

    @classmethod
    def for_activity(
        cls,
        activity: HarnessGraphActivity,
        *,
        task: Mapping[str, Any],
        leaf_activity_kind: HarnessLeafActivityKind | str,
        required_usage: HarnessActivityUsage | str,
        graph_checkpoint_ref: str,
        output_keys: tuple[str, ...],
        timeout_seconds: float | None = None,
    ) -> HarnessGraphActivityExecutionInput:
        if not isinstance(activity, HarnessGraphActivity):
            raise TypeError("activity must be HarnessGraphActivity")
        value = cls(
            activity_id=activity.activity_id,
            activity_checksum=activity.activity_checksum,
            task=task,
            leaf_activity_kind=leaf_activity_kind,
            required_usage=required_usage,
            graph_checkpoint_ref=graph_checkpoint_ref,
            output_keys=output_keys,
            timeout_seconds=timeout_seconds,
        )
        value.assert_matches(activity)
        return value

    def assert_matches(self, activity: HarnessGraphActivity) -> None:
        if not isinstance(activity, HarnessGraphActivity):
            raise TypeError("activity must be HarnessGraphActivity")
        mismatches = tuple(
            field_name
            for field_name, expected, actual in (
                ("activity_id", activity.activity_id, self.activity_id),
                ("activity_checksum", activity.activity_checksum, self.activity_checksum),
                ("input_ref", activity.input_ref, self.input_ref),
            )
            if expected != actual
        )
        if mismatches:
            raise HarnessValidationError(
                "resolved execution input conflicts with its durable Graph activity",
                code="graph_activity_execution_input_mismatch",
                details={"mismatches": list(mismatches)},
            )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "activity_id": self.activity_id,
            "activity_checksum": self.activity_checksum,
            "task": mapping_to_dict(self.task),
            "leaf_activity_kind": self.leaf_activity_kind.value,
            "required_usage": self.required_usage.value,
            "graph_checkpoint_ref": self.graph_checkpoint_ref,
            "output_keys": list(self.output_keys),
            "timeout_seconds": self.timeout_seconds,
            "input_ref": self.input_ref,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "binding_checksum": self.binding_checksum}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HarnessGraphActivityExecutionInput:
        expected = {
            "schema_version", "activity_id", "activity_checksum", "task",
            "leaf_activity_kind", "required_usage", "graph_checkpoint_ref",
            "output_keys", "timeout_seconds", "input_ref", "binding_checksum",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise HarnessValidationError(
                "Graph activity execution input fields are invalid",
                code="graph_activity_execution_input_invalid",
            )
        output_keys = value["output_keys"]
        if isinstance(output_keys, str | bytes) or not isinstance(output_keys, Sequence):
            raise HarnessValidationError(
                "Graph activity execution output keys must be an array",
                code="graph_activity_execution_input_invalid",
            )
        restored = cls(
            activity_id=value["activity_id"],
            activity_checksum=value["activity_checksum"],
            task=value["task"],
            leaf_activity_kind=value["leaf_activity_kind"],
            required_usage=value["required_usage"],
            graph_checkpoint_ref=value["graph_checkpoint_ref"],
            output_keys=tuple(output_keys),
            timeout_seconds=value["timeout_seconds"],
            schema_version=value["schema_version"],
        )
        if (
            value["input_ref"] != restored.input_ref
            or value["binding_checksum"] != restored.binding_checksum
        ):
            raise HarnessValidationError(
                "Graph activity execution input checksum is invalid",
                code="graph_activity_execution_input_checksum_invalid",
            )
        return restored


@dataclass(frozen=True, slots=True)
class HarnessGraphActivityTaskContext:
    """Harness-owned worker context for one checkpoint-bound Graph activity."""

    activity: HarnessGraphActivity
    graph_checkpoint_ref: str
    schema_version: str = HARNESS_GRAPH_ACTIVITY_TASK_CONTEXT_SCHEMA
    context_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.activity, HarnessGraphActivity):
            raise TypeError("activity must be HarnessGraphActivity")
        object.__setattr__(
            self,
            "graph_checkpoint_ref",
            required_text(
                self.graph_checkpoint_ref,
                "graph_activity_task_context.graph_checkpoint_ref",
            ),
        )
        if self.schema_version != HARNESS_GRAPH_ACTIVITY_TASK_CONTEXT_SCHEMA:
            raise HarnessValidationError(
                "unsupported Graph activity task context schema",
                code="unsupported_graph_activity_task_context_schema",
            )
        object.__setattr__(
            self,
            "context_checksum",
            canonical_checksum(self.checksum_projection()),
        )

    @classmethod
    def for_execution_input(
        cls,
        activity: HarnessGraphActivity,
        execution_input: HarnessGraphActivityExecutionInput,
    ) -> HarnessGraphActivityTaskContext:
        if not isinstance(execution_input, HarnessGraphActivityExecutionInput):
            raise TypeError("execution_input must be HarnessGraphActivityExecutionInput")
        execution_input.assert_matches(activity)
        return cls(
            activity=activity,
            graph_checkpoint_ref=execution_input.graph_checkpoint_ref,
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "activity": self.activity.to_dict(),
            "graph_checkpoint_ref": self.graph_checkpoint_ref,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "context_checksum": self.context_checksum}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HarnessGraphActivityTaskContext:
        expected = {
            "schema_version", "activity", "graph_checkpoint_ref", "context_checksum"
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise HarnessValidationError(
                "Graph activity task context fields are invalid",
                code="graph_activity_task_context_invalid",
            )
        activity = value["activity"]
        if not isinstance(activity, Mapping):
            raise HarnessValidationError(
                "Graph activity task context activity must be an object",
                code="graph_activity_task_context_invalid",
            )
        context = cls(
            activity=HarnessGraphActivity.from_dict(activity),
            graph_checkpoint_ref=value["graph_checkpoint_ref"],
            schema_version=value["schema_version"],
        )
        if value["context_checksum"] != context.context_checksum:
            raise HarnessValidationError(
                "Graph activity task context checksum does not match",
                code="graph_activity_task_context_checksum_invalid",
            )
        return context


@runtime_checkable
class HarnessGraphActivityExecutionInputResolverPort(Protocol):
    def resolve_execution_input(
        self,
        activity: HarnessGraphActivity,
    ) -> HarnessGraphActivityExecutionInput:
        """Resolve immutable input already bound to the activity input ref."""


@runtime_checkable
class HarnessGraphActivityExecutionCommitPort(Protocol):
    def commit_execution_result(
        self,
        *,
        activity: HarnessGraphActivity,
        execution_input: HarnessGraphActivityExecutionInput,
        worker_result: HarnessWorkerResult | None,
        node_output_commit: HarnessNodeOutputCommit | None,
        result: HarnessGraphActivityResult,
    ) -> HarnessGraphActivityResult:
        """Idempotently commit one activity-bound result and return its fact."""


def _output_keys(values: Any) -> tuple[str, ...]:
    if isinstance(values, str | bytes) or not isinstance(values, Sequence):
        raise HarnessValidationError(
            "Graph candidate activity requires declared output keys",
            code="graph_activity_execution_output_keys_invalid",
        )
    normalized = tuple(
        required_text(value, "activity_execution_input.output_key") for value in values
    )
    if not normalized or len(normalized) != len(set(normalized)):
        raise HarnessValidationError(
            "Graph candidate activity requires unique non-empty output keys",
            code="graph_activity_execution_output_keys_invalid",
        )
    return normalized


def _checksum(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
        raise HarnessValidationError(
            f"{field_name} must be a sha256 reference",
            code="graph_activity_execution_reference_invalid",
        )
    try:
        int(value.removeprefix("sha256:"), 16)
    except ValueError as exc:
        raise HarnessValidationError(
            f"{field_name} must be a sha256 reference",
            code="graph_activity_execution_reference_invalid",
        ) from exc
    return value


__all__ = [
    "HARNESS_GRAPH_ACTIVITY_EXECUTION_INPUT_SCHEMA",
    "HARNESS_GRAPH_ACTIVITY_FAILURE_EVIDENCE_SCHEMA",
    "HARNESS_GRAPH_ACTIVITY_TASK_CONTEXT_KEY",
    "HARNESS_GRAPH_ACTIVITY_TASK_CONTEXT_SCHEMA",
    "HarnessGraphActivityExecutionCommitPort",
    "HarnessGraphActivityExecutionInput",
    "HarnessGraphActivityExecutionInputResolverPort",
    "HarnessGraphActivityTaskContext",
]
