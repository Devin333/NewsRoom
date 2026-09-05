from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable

from framework.agent.models.action import DelegateBatchCandidate
from framework.shared.graph_identity import GraphExecutionIdentity
from framework.shared.redaction import redact_sensitive_values


AGENT_ORCHESTRATION_REQUEST_SCHEMA = "newsroom.agent-orchestration-request/v1"
AGENT_ORCHESTRATION_RESULT_SCHEMA = "newsroom.agent-orchestration-result/v1"
PARENT_OBSERVATION_SCHEMA = "newsroom.parent-observation/v1"


@dataclass(frozen=True, slots=True)
class ParentObservationLimits:
    """Trusted policy limits for the one joined parent observation."""

    max_task_summaries: int = 8
    max_summary_bytes: int = 2048
    max_diagnostics: int = 16
    max_refs: int = 16
    max_observation_bytes: int = 16384

    def __post_init__(self) -> None:
        for field_name in (
            "max_task_summaries",
            "max_summary_bytes",
            "max_diagnostics",
            "max_refs",
            "max_observation_bytes",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")

    def to_dict(self) -> dict[str, int]:
        return {
            "max_task_summaries": self.max_task_summaries,
            "max_summary_bytes": self.max_summary_bytes,
            "max_diagnostics": self.max_diagnostics,
            "max_refs": self.max_refs,
            "max_observation_bytes": self.max_observation_bytes,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ParentObservationLimits":
        return cls(**_strict_fields(value, set(cls.__dataclass_fields__)))


@dataclass(frozen=True, slots=True)
class ParentTaskSummary:
    logical_task_id: str
    status: str
    summary: str | None = None
    result_ref: str | None = None
    result_checksum: str | None = None
    output_roles: tuple[str, ...] = ()
    terminal_reason: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("logical_task_id", "status"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        for field_name in ("summary", "result_ref", "result_checksum", "terminal_reason"):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string or None")
        output_roles = tuple(self.output_roles)
        if any(not isinstance(item, str) or not item.strip() for item in output_roles):
            raise TypeError("output_roles must contain non-empty strings")
        object.__setattr__(self, "output_roles", output_roles)

    def to_dict(self) -> dict[str, Any]:
        return {
            "logical_task_id": self.logical_task_id,
            "status": self.status,
            "summary": self.summary,
            "result_ref": self.result_ref,
            "result_checksum": self.result_checksum,
            "output_roles": list(self.output_roles),
            "terminal_reason": self.terminal_reason,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ParentTaskSummary":
        payload = _strict_fields(
            value,
            set(cls.__dataclass_fields__),
            optional={"output_roles", "terminal_reason"},
        )
        payload.setdefault("output_roles", ())
        payload.setdefault("terminal_reason", None)
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class ParentWaveSummary:
    wave_id: str
    ordinal: int
    status: str
    task_ids: tuple[str, ...] = ()
    effective_parallelism: int = 0
    degraded_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.wave_id, str) or not self.wave_id.strip():
            raise ValueError("wave_id must be a non-empty string")
        if isinstance(self.ordinal, bool) or not isinstance(self.ordinal, int) or self.ordinal < 1:
            raise ValueError("ordinal must be a positive integer")
        if not isinstance(self.status, str) or not self.status.strip():
            raise ValueError("status must be a non-empty string")
        task_ids = tuple(self.task_ids)
        if any(not isinstance(item, str) or not item.strip() for item in task_ids):
            raise TypeError("task_ids must contain non-empty strings")
        if (
            isinstance(self.effective_parallelism, bool)
            or not isinstance(self.effective_parallelism, int)
            or self.effective_parallelism < 0
        ):
            raise ValueError("effective_parallelism must be a non-negative integer")
        if self.degraded_reason is not None and not isinstance(self.degraded_reason, str):
            raise TypeError("degraded_reason must be a string or None")
        object.__setattr__(self, "task_ids", task_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "wave_id": self.wave_id,
            "ordinal": self.ordinal,
            "status": self.status,
            "task_ids": list(self.task_ids),
            "effective_parallelism": self.effective_parallelism,
            "degraded_reason": self.degraded_reason,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ParentWaveSummary":
        payload = _strict_fields(
            value,
            set(cls.__dataclass_fields__),
            optional={"task_ids", "effective_parallelism", "degraded_reason"},
        )
        payload.setdefault("task_ids", ())
        payload.setdefault("effective_parallelism", 0)
        payload.setdefault("degraded_reason", None)
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class ParentObservation:
    """Only security-projected, bounded child evidence may cross to the parent."""

    group_id: str
    group_status: str
    plan_version: str
    task_summaries: tuple[ParentTaskSummary, ...] = ()
    wave_summaries: tuple[ParentWaveSummary, ...] = ()
    aggregate_ref: str | None = None
    aggregate_checksum: str | None = None
    diagnostics: tuple[str, ...] = ()
    result_refs: tuple[str, ...] = ()
    run_id: str | None = None
    stage_id: str | None = None
    correlation_id: str | None = None
    requested_parallelism: int = 0
    effective_parallelism: int = 0
    budget_usage: Mapping[str, Any] = field(default_factory=dict)
    retry_count: int = 0
    replan_count: int = 0
    recovery_outcome: str | None = None
    degraded_reason: str | None = None
    terminal_reason: str | None = None
    required_output_roles: tuple[str, ...] = ()
    covered_output_roles: tuple[str, ...] = ()
    schema_version: str = PARENT_OBSERVATION_SCHEMA

    def __post_init__(self) -> None:
        for field_name in ("group_id", "group_status", "plan_version"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if self.schema_version != PARENT_OBSERVATION_SCHEMA:
            raise ValueError("unsupported parent observation schema")
        task_summaries = tuple(self.task_summaries)
        waves = tuple(self.wave_summaries)
        diagnostics = tuple(self.diagnostics)
        refs = tuple(self.result_refs)
        if not all(isinstance(item, ParentTaskSummary) for item in task_summaries):
            raise TypeError("task_summaries must contain ParentTaskSummary values")
        if not all(isinstance(item, ParentWaveSummary) for item in waves):
            raise TypeError("wave_summaries must contain ParentWaveSummary values")
        if any(not isinstance(item, str) for item in diagnostics + refs):
            raise TypeError("diagnostics and result_refs must contain strings")
        for field_name in (
            "run_id",
            "stage_id",
            "correlation_id",
            "recovery_outcome",
            "degraded_reason",
            "terminal_reason",
        ):
            value = getattr(self, field_name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{field_name} must be a non-empty string or None")
        for field_name in (
            "requested_parallelism",
            "effective_parallelism",
            "retry_count",
            "replan_count",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        budget_usage = self.budget_usage or {}
        if not isinstance(budget_usage, Mapping):
            raise TypeError("budget_usage must be a mapping")
        roles = {}
        for field_name in ("required_output_roles", "covered_output_roles"):
            values = tuple(getattr(self, field_name))
            if any(not isinstance(item, str) or not item.strip() for item in values):
                raise TypeError(f"{field_name} must contain non-empty strings")
            roles[field_name] = values
        if (self.aggregate_ref is None) != (self.aggregate_checksum is None):
            raise ValueError("aggregate_ref and aggregate_checksum must appear together")
        checksum_bound_refs = {
            item.result_ref
            for item in task_summaries
            if item.result_ref is not None and item.result_checksum is not None
        }
        if self.aggregate_ref is not None:
            checksum_bound_refs.add(self.aggregate_ref)
        if not set(refs).issubset(checksum_bound_refs):
            raise ValueError("result_refs must be checksum-bound task or aggregate references")
        object.__setattr__(self, "task_summaries", task_summaries)
        object.__setattr__(self, "wave_summaries", tuple(sorted(waves, key=lambda item: item.ordinal)))
        object.__setattr__(self, "diagnostics", diagnostics)
        object.__setattr__(self, "result_refs", refs)
        object.__setattr__(self, "budget_usage", dict(budget_usage))
        for field_name, values in roles.items():
            object.__setattr__(self, field_name, values)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "group_id": self.group_id,
            "group_status": self.group_status,
            "plan_version": self.plan_version,
            "task_summaries": [item.to_dict() for item in self.task_summaries],
            "wave_summaries": [item.to_dict() for item in self.wave_summaries],
            "aggregate_ref": self.aggregate_ref,
            "aggregate_checksum": self.aggregate_checksum,
            "diagnostics": list(self.diagnostics),
            "result_refs": list(self.result_refs),
            "run_id": self.run_id,
            "stage_id": self.stage_id,
            "correlation_id": self.correlation_id,
            "requested_parallelism": self.requested_parallelism,
            "effective_parallelism": self.effective_parallelism,
            "budget_usage": dict(self.budget_usage),
            "retry_count": self.retry_count,
            "replan_count": self.replan_count,
            "recovery_outcome": self.recovery_outcome,
            "degraded_reason": self.degraded_reason,
            "terminal_reason": self.terminal_reason,
            "required_output_roles": list(self.required_output_roles),
            "covered_output_roles": list(self.covered_output_roles),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ParentObservation":
        payload = _strict_fields(
            value,
            set(cls.__dataclass_fields__),
            optional={
                "run_id", "stage_id", "correlation_id", "requested_parallelism",
                "effective_parallelism", "budget_usage", "retry_count", "replan_count",
                "recovery_outcome", "degraded_reason", "terminal_reason",
                "required_output_roles", "covered_output_roles",
            },
        )
        for field_name, default in {
            "run_id": None,
            "stage_id": None,
            "correlation_id": None,
            "requested_parallelism": 0,
            "effective_parallelism": 0,
            "budget_usage": {},
            "retry_count": 0,
            "replan_count": 0,
            "recovery_outcome": None,
            "degraded_reason": None,
            "terminal_reason": None,
            "required_output_roles": (),
            "covered_output_roles": (),
        }.items():
            payload.setdefault(field_name, default)
        tasks = payload.get("task_summaries", ())
        waves = payload.get("wave_summaries", ())
        if not isinstance(tasks, list) or not isinstance(waves, list):
            raise TypeError("task_summaries and wave_summaries must be arrays")
        payload["task_summaries"] = tuple(
            ParentTaskSummary.from_dict(item) for item in tasks
        )
        payload["wave_summaries"] = tuple(
            ParentWaveSummary.from_dict(item) for item in waves
        )
        return cls(**payload)

    def project(self, limits: ParentObservationLimits) -> dict[str, Any]:
        """Redact, truncate, and bound content before it becomes an LLM observation."""
        tasks = [item.to_dict() for item in self.task_summaries[: limits.max_task_summaries]]
        detail_truncated = False
        for task in tasks:
            if task["summary"] is not None:
                summary = str(redact_sensitive_values(task["summary"]))
                task["summary"] = truncate_observation_text(summary, limits.max_summary_bytes)
                detail_truncated |= task["summary"] != summary
        diagnostics = []
        for item in self.diagnostics[: limits.max_diagnostics]:
            diagnostic = str(redact_sensitive_values(item))
            bounded_diagnostic = truncate_observation_text(diagnostic, limits.max_summary_bytes)
            diagnostics.append(bounded_diagnostic)
            detail_truncated |= bounded_diagnostic != diagnostic
        payload = {
            "schema_version": self.schema_version,
            "group_id": self.group_id,
            "group_status": self.group_status,
            "plan_version": self.plan_version,
            "waves": [item.to_dict() for item in self.wave_summaries],
            "tasks": tasks,
            "aggregate_ref": self.aggregate_ref,
            "aggregate_checksum": self.aggregate_checksum,
            "diagnostics": diagnostics,
            "result_refs": _project_checksum_bound_refs(
                task_summaries=tasks,
                aggregate_ref=self.aggregate_ref,
                requested_refs=self.result_refs,
                max_refs=limits.max_refs,
            ),
            "run_id": self.run_id,
            "stage_id": self.stage_id,
            "correlation_id": self.correlation_id,
            "requested_parallelism": self.requested_parallelism,
            "effective_parallelism": self.effective_parallelism,
            "budget_usage": dict(self.budget_usage),
            "retry_count": self.retry_count,
            "replan_count": self.replan_count,
            "recovery_outcome": self.recovery_outcome,
            "degraded_reason": self.degraded_reason,
            "terminal_reason": self.terminal_reason,
            "required_output_roles": list(self.required_output_roles),
            "covered_output_roles": list(self.covered_output_roles),
            "truncated": (
                detail_truncated
                or len(self.task_summaries) > len(tasks)
                or len(self.diagnostics) > limits.max_diagnostics
                or len(self.result_refs) > limits.max_refs
            ),
        }
        payload = redact_sensitive_values(payload)
        return _fit_parent_observation(payload, limits.max_observation_bytes)


@dataclass(frozen=True, slots=True)
class AgentOrchestrationRequest:
    parent_agent_id: str
    run_id: str | None
    execution_identity: GraphExecutionIdentity | None
    graph_checkpoint_ref: str | None
    policy_ref: str
    max_tasks_per_group: int
    parent_observation_limits: ParentObservationLimits
    candidate: DelegateBatchCandidate
    schema_version: str = AGENT_ORCHESTRATION_REQUEST_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.parent_agent_id, str) or not self.parent_agent_id.strip():
            raise ValueError("parent_agent_id must be a non-empty string")
        if self.run_id is not None and (not isinstance(self.run_id, str) or not self.run_id.strip()):
            raise ValueError("run_id must be a canonical string or None")
        if self.execution_identity is not None and not isinstance(self.execution_identity, GraphExecutionIdentity):
            raise TypeError("execution_identity must be GraphExecutionIdentity or None")
        if self.execution_identity is not None and self.run_id != self.execution_identity.run_id:
            raise ValueError("run_id must match execution_identity")
        if not isinstance(self.policy_ref, str) or not self.policy_ref.strip():
            raise ValueError("policy_ref must be a non-empty string")
        if isinstance(self.max_tasks_per_group, bool) or not isinstance(self.max_tasks_per_group, int) or self.max_tasks_per_group < 1:
            raise ValueError("max_tasks_per_group must be a positive integer")
        if len(self.candidate.tasks) > self.max_tasks_per_group:
            raise ValueError("delegate_batch exceeds max_tasks_per_group")
        if (
            self.candidate.parallelism_hint is not None
            and self.candidate.parallelism_hint > self.max_tasks_per_group
        ):
            raise ValueError("delegate_batch parallelism_hint exceeds max_tasks_per_group")
        if not isinstance(self.parent_observation_limits, ParentObservationLimits):
            raise TypeError("parent_observation_limits must be ParentObservationLimits")
        if self.schema_version != AGENT_ORCHESTRATION_REQUEST_SCHEMA:
            raise ValueError("unsupported orchestration request schema")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "parent_agent_id": self.parent_agent_id,
            "run_id": self.run_id,
            "execution_identity": (
                self.execution_identity.to_dict()
                if self.execution_identity is not None
                else None
            ),
            "graph_checkpoint_ref": self.graph_checkpoint_ref,
            "policy_ref": self.policy_ref,
            "max_tasks_per_group": self.max_tasks_per_group,
            "parent_observation_limits": self.parent_observation_limits.to_dict(),
            "candidate": self.candidate.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AgentOrchestrationRequest":
        payload = _strict_fields(value, set(cls.__dataclass_fields__))
        raw_identity = payload.get("execution_identity")
        if raw_identity is not None:
            payload["execution_identity"] = GraphExecutionIdentity.from_dict(raw_identity)
        payload["parent_observation_limits"] = ParentObservationLimits.from_dict(
            payload["parent_observation_limits"]
        )
        payload["candidate"] = DelegateBatchCandidate.from_dict(payload["candidate"])
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class AgentOrchestrationResult:
    status: str
    observation: ParentObservation
    reason_code: str | None = None
    schema_version: str = AGENT_ORCHESTRATION_RESULT_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.status, str) or not self.status.strip():
            raise ValueError("orchestration status must be a non-empty string")
        if not isinstance(self.observation, ParentObservation):
            raise TypeError("observation must be ParentObservation")
        if self.reason_code is not None and not isinstance(self.reason_code, str):
            raise TypeError("reason_code must be a string or None")
        if self.schema_version != AGENT_ORCHESTRATION_RESULT_SCHEMA:
            raise ValueError("unsupported orchestration result schema")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "observation": self.observation.to_dict(),
            "reason_code": self.reason_code,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AgentOrchestrationResult":
        payload = _strict_fields(value, set(cls.__dataclass_fields__))
        payload["observation"] = ParentObservation.from_dict(payload["observation"])
        return cls(**payload)


@runtime_checkable
class AgentOrchestrationPort(Protocol):
    """Harness-owned boundary; AgentLoop may submit but never execute children."""

    def dispatch(self, request: AgentOrchestrationRequest) -> AgentOrchestrationResult: ...


def truncate_observation_text(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    suffix = "." * min(max_bytes, 3)
    limit = max_bytes - len(suffix)
    return encoded[:limit].decode("utf-8", errors="ignore") + suffix


def _strict_fields(
    value: Mapping[str, Any],
    expected: set[str],
    *,
    optional: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("orchestration contract must be an object")
    actual = set(value)
    unknown = sorted(actual - expected)
    missing = sorted(expected - actual - (optional or set()))
    if unknown or missing:
        raise ValueError(
            "orchestration contract has unknown fields "
            f"{unknown} or missing fields {missing}"
        )
    return dict(value)


def _project_checksum_bound_refs(
    *,
    task_summaries: list[dict[str, Any]],
    aggregate_ref: str | None,
    requested_refs: tuple[str, ...],
    max_refs: int,
) -> list[str]:
    task_refs = {
        item["result_ref"]
        for item in task_summaries
        if item["result_ref"] is not None and item["result_checksum"] is not None
    }
    permitted = task_refs | ({aggregate_ref} if aggregate_ref is not None else set())
    return [ref for ref in requested_refs if ref in permitted][:max_refs]


def _fit_parent_observation(payload: dict[str, Any], max_observation_bytes: int) -> dict[str, Any]:
    """Drop only bounded detail until the serialized parent view fits its policy."""

    payload = dict(payload)
    # Keep legacy diagnostic visibility by shedding optional telemetry first
    # when the caller uses a very small observation budget.
    for field_name in (
        "budget_usage",
        "required_output_roles",
        "covered_output_roles",
        "correlation_id",
        "run_id",
        "stage_id",
        "requested_parallelism",
        "effective_parallelism",
        "retry_count",
        "replan_count",
        "recovery_outcome",
        "degraded_reason",
        "terminal_reason",
    ):
        if _encoded_bytes(payload) <= max_observation_bytes:
            break
        payload.pop(field_name, None)
        payload["truncated"] = True
    for field_name in ("diagnostics", "result_refs", "waves", "tasks"):
        values = list(payload[field_name])
        while _encoded_bytes(payload) > max_observation_bytes and values:
            values.pop()
            payload[field_name] = values
            payload["truncated"] = True
    if _encoded_bytes(payload) > max_observation_bytes:
        # Aggregate evidence remains reachable through the durable group record.
        payload["aggregate_ref"] = None
        payload["aggregate_checksum"] = None
        payload["truncated"] = True
    if _encoded_bytes(payload) > max_observation_bytes:
        raise ValueError("ParentObservationLimits.max_observation_bytes cannot represent group identity")
    return payload


def _encoded_bytes(value: dict[str, Any]) -> int:
    return len(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    )


__all__ = [
    "AGENT_ORCHESTRATION_REQUEST_SCHEMA",
    "AGENT_ORCHESTRATION_RESULT_SCHEMA",
    "PARENT_OBSERVATION_SCHEMA",
    "AgentOrchestrationPort",
    "AgentOrchestrationRequest",
    "AgentOrchestrationResult",
    "ParentObservation",
    "ParentObservationLimits",
    "truncate_observation_text",
    "ParentTaskSummary",
    "ParentWaveSummary",
]
