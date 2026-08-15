"""Low-cardinality Harness graph metrics and bounded operator diagnostics."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_state import (
    HarnessCompensationStatus,
    HarnessGraphState,
    HarnessWaitStatus,
    RunOutcome,
)
from framework.harness.graph.canonical import required_text


class HarnessGraphHealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class HarnessGraphDiagnosticSeverity(StrEnum):
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class HarnessGraphMetricSample:
    name: str
    value: float
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", required_text(self.name, "metric.name"))
        if not isinstance(self.value, int | float) or isinstance(self.value, bool):
            raise TypeError("metric value must be numeric")
        labels = dict(self.labels)
        allowed = {"lifecycle", "outcome", "result"}
        if set(labels).difference(allowed):
            raise HarnessValidationError(
                "graph metric contains a high-cardinality label",
                code="graph_metric_label_rejected",
            )
        object.__setattr__(
            self,
            "labels",
            MappingProxyType({key: str(labels[key]) for key in sorted(labels)}),
        )
        object.__setattr__(self, "value", float(self.value))

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "value": self.value, "labels": dict(self.labels)}


@dataclass(frozen=True, slots=True)
class HarnessGraphOperatorDiagnostic:
    code: str
    severity: HarnessGraphDiagnosticSeverity | str
    evidence_refs: tuple[str, ...] = ()
    current_value: int | None = None
    threshold: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", required_text(self.code, "diagnostic.code"))
        object.__setattr__(
            self,
            "severity",
            HarnessGraphDiagnosticSeverity(self.severity),
        )
        refs = tuple(sorted(str(item) for item in self.evidence_refs))
        if any(not _is_checksum(item) for item in refs):
            raise HarnessValidationError(
                "operator diagnostics may expose checksum evidence only",
                code="graph_diagnostic_reference_rejected",
            )
        object.__setattr__(self, "evidence_refs", refs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "evidence_refs": list(self.evidence_refs),
            "current_value": self.current_value,
            "threshold": self.threshold,
        }


@dataclass(frozen=True, slots=True)
class HarnessGraphHealthReport:
    status: HarnessGraphHealthStatus | str
    diagnostics: tuple[HarnessGraphOperatorDiagnostic, ...]
    last_event_sequence: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", HarnessGraphHealthStatus(self.status))
        diagnostics = tuple(self.diagnostics)
        if not all(
            isinstance(item, HarnessGraphOperatorDiagnostic) for item in diagnostics
        ):
            raise TypeError("diagnostics must contain HarnessGraphOperatorDiagnostic")
        object.__setattr__(
            self,
            "diagnostics",
            tuple(sorted(diagnostics, key=lambda item: (item.severity.value, item.code))),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "last_event_sequence": self.last_event_sequence,
        }


def graph_metric_samples(
    state: HarnessGraphState,
    *,
    decision_latency_ms: float | None = None,
    replay_mismatch: bool = False,
    validation_failure: bool = False,
) -> tuple[HarnessGraphMetricSample, ...]:
    if not isinstance(state, HarnessGraphState):
        raise TypeError("state must be HarnessGraphState")
    labels = {"lifecycle": state.lifecycle.value, "outcome": state.outcome.value}
    parallel_limit = state.budgets.get("max_parallelism")
    compensation_done = sum(
        item.status
        in {
            HarnessCompensationStatus.SUCCEEDED,
            HarnessCompensationStatus.FAILED,
            HarnessCompensationStatus.INDETERMINATE,
        }
        for item in state.compensation_stack
    )
    unresolved_wait_ages = tuple(
        state.last_event_sequence - item.registered_sequence
        for item in state.wait_registrations
        if item.status is HarnessWaitStatus.REGISTERED
    )
    values = {
        "harness_graph_active_nodes": len(state.running_node_ids),
        "harness_graph_ready_nodes": len(state.ready_node_ids),
        "harness_graph_waiting_nodes": len(state.waiting_node_ids),
        "harness_graph_parallel_admission": len(state.active_activities),
        "harness_graph_parallel_limit": (
            0 if parallel_limit is None else parallel_limit.limit
        ),
        "harness_graph_loop_iterations": sum(
            item.completed_iterations for item in state.loop_counters
        ),
        "harness_graph_wait_age_sequences": max(unresolved_wait_ages, default=0),
        "harness_graph_compensation_total": len(state.compensation_stack),
        "harness_graph_compensation_completed": compensation_done,
        "harness_graph_replay_mismatch": int(replay_mismatch),
        "harness_graph_validation_failure": int(validation_failure),
    }
    samples = [HarnessGraphMetricSample(name, value, labels) for name, value in values.items()]
    if decision_latency_ms is not None:
        if decision_latency_ms < 0:
            raise HarnessValidationError(
                "decision latency cannot be negative",
                code="invalid_graph_decision_latency",
            )
        samples.append(
            HarnessGraphMetricSample(
                "harness_graph_decision_latency_ms",
                decision_latency_ms,
                labels,
            )
        )
    return tuple(samples)


def graph_health_report(
    state: HarnessGraphState,
    *,
    canonical_high_watermark: int | None = None,
    stuck_wait_sequence_threshold: int = 1_000,
    event_lag_threshold: int = 100,
    incompatible_history: bool = False,
) -> HarnessGraphHealthReport:
    if not isinstance(state, HarnessGraphState):
        raise TypeError("state must be HarnessGraphState")
    for name, value in (
        ("stuck_wait_sequence_threshold", stuck_wait_sequence_threshold),
        ("event_lag_threshold", event_lag_threshold),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise HarnessValidationError(
                f"{name} must be a nonnegative integer",
                code="invalid_graph_health_policy",
            )
    diagnostics: list[HarnessGraphOperatorDiagnostic] = []
    for wait in state.wait_registrations:
        age = state.last_event_sequence - wait.registered_sequence
        if wait.unresolved and age > stuck_wait_sequence_threshold:
            diagnostics.append(
                HarnessGraphOperatorDiagnostic(
                    "stuck_wait",
                    "warning",
                    current_value=age,
                    threshold=stuck_wait_sequence_threshold,
                )
            )
    if state.outcome is RunOutcome.INDETERMINATE:
        diagnostics.append(
            HarnessGraphOperatorDiagnostic(
                "indeterminate_activity",
                "error",
                evidence_refs=(
                    ()
                    if state.terminal_evidence_ref is None
                    else (state.terminal_evidence_ref,)
                ),
            )
        )
    failed_compensation_refs = tuple(
        item.outcome_ref
        for item in state.compensation_stack
        if item.status
        in {HarnessCompensationStatus.FAILED, HarnessCompensationStatus.INDETERMINATE}
        and item.outcome_ref is not None
    )
    if failed_compensation_refs:
        diagnostics.append(
            HarnessGraphOperatorDiagnostic(
                "compensation_failure",
                "error",
                evidence_refs=failed_compensation_refs,
            )
        )
    if canonical_high_watermark is not None:
        if canonical_high_watermark < state.last_event_sequence:
            diagnostics.append(
                HarnessGraphOperatorDiagnostic(
                    "history_high_watermark_regression",
                    "error",
                    current_value=canonical_high_watermark,
                    threshold=state.last_event_sequence,
                )
            )
        else:
            lag = canonical_high_watermark - state.last_event_sequence
            if lag > event_lag_threshold:
                diagnostics.append(
                    HarnessGraphOperatorDiagnostic(
                        "event_projection_lag",
                        "warning",
                        current_value=lag,
                        threshold=event_lag_threshold,
                    )
                )
    if incompatible_history:
        diagnostics.append(
            HarnessGraphOperatorDiagnostic("incompatible_history", "error")
        )
    status = HarnessGraphHealthStatus.HEALTHY
    if any(item.severity is HarnessGraphDiagnosticSeverity.ERROR for item in diagnostics):
        status = HarnessGraphHealthStatus.UNHEALTHY
    elif diagnostics:
        status = HarnessGraphHealthStatus.DEGRADED
    return HarnessGraphHealthReport(status, tuple(diagnostics), state.last_event_sequence)


def _is_checksum(value: str) -> bool:
    return (
        len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


__all__ = [
    "HarnessGraphDiagnosticSeverity",
    "HarnessGraphHealthReport",
    "HarnessGraphHealthStatus",
    "HarnessGraphMetricSample",
    "HarnessGraphOperatorDiagnostic",
    "graph_health_report",
    "graph_metric_samples",
]
