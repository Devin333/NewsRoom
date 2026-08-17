"""Low-cardinality Harness graph metrics and bounded operator diagnostics."""

from __future__ import annotations

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_state import (
    HarnessCompensationStatus,
    HarnessGraphState,
    HarnessWaitStatus,
    RunOutcome,
)
from framework.harness.graph.observability import (
    HarnessGraphDiagnosticSeverity as _HarnessGraphDiagnosticSeverity,
    HarnessGraphHealthReport as _HarnessGraphHealthReport,
    HarnessGraphHealthStatus as _HarnessGraphHealthStatus,
    HarnessGraphMetricSample as _HarnessGraphMetricSample,
    HarnessGraphOperatorDiagnostic as _HarnessGraphOperatorDiagnostic,
)


def graph_metric_samples(
    state: HarnessGraphState,
    *,
    decision_latency_ms: float | None = None,
    replay_mismatch: bool = False,
    validation_failure: bool = False,
) -> tuple[_HarnessGraphMetricSample, ...]:
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
    samples = [
        _HarnessGraphMetricSample(name, value, labels)
        for name, value in values.items()
    ]
    if decision_latency_ms is not None:
        if decision_latency_ms < 0:
            raise HarnessValidationError(
                "decision latency cannot be negative",
                code="invalid_graph_decision_latency",
            )
        samples.append(
            _HarnessGraphMetricSample(
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
) -> _HarnessGraphHealthReport:
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
    diagnostics: list[_HarnessGraphOperatorDiagnostic] = []
    for wait in state.wait_registrations:
        age = state.last_event_sequence - wait.registered_sequence
        if wait.unresolved and age > stuck_wait_sequence_threshold:
            diagnostics.append(
                _HarnessGraphOperatorDiagnostic(
                    "stuck_wait",
                    "warning",
                    current_value=age,
                    threshold=stuck_wait_sequence_threshold,
                )
            )
    if state.outcome is RunOutcome.INDETERMINATE:
        diagnostics.append(
            _HarnessGraphOperatorDiagnostic(
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
            _HarnessGraphOperatorDiagnostic(
                "compensation_failure",
                "error",
                evidence_refs=failed_compensation_refs,
            )
        )
    if canonical_high_watermark is not None:
        if canonical_high_watermark < state.last_event_sequence:
            diagnostics.append(
                _HarnessGraphOperatorDiagnostic(
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
                    _HarnessGraphOperatorDiagnostic(
                        "event_projection_lag",
                        "warning",
                        current_value=lag,
                        threshold=event_lag_threshold,
                    )
                )
    if incompatible_history:
        diagnostics.append(
            _HarnessGraphOperatorDiagnostic("incompatible_history", "error")
        )
    status = _HarnessGraphHealthStatus.HEALTHY
    if any(
        item.severity is _HarnessGraphDiagnosticSeverity.ERROR
        for item in diagnostics
    ):
        status = _HarnessGraphHealthStatus.UNHEALTHY
    elif diagnostics:
        status = _HarnessGraphHealthStatus.DEGRADED
    return _HarnessGraphHealthReport(status, tuple(diagnostics), state.last_event_sequence)


__all__ = [
    "graph_health_report",
    "graph_metric_samples",
]
