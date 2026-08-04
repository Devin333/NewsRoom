from __future__ import annotations

from dataclasses import dataclass

from framework.events.trace import TraceContext
from framework.shared.attempt_events import (
    attempt_rejection_event_payload,
    attempt_started_event_payload,
    attempt_terminal_event_payload,
)
from framework.shared.attempts import (
    AdmissionResult,
    AttemptContext,
    AttemptOutcome,
    AttemptState,
)
from framework.shared.errors import RuntimeExecutionError
from framework.workflow.runtime.event_emitter import WorkflowEventRecorder


@dataclass(frozen=True, slots=True)
class WorkflowDurableAttemptSink:
    """Project shared attempt lifecycle facts into the workflow event stream."""

    required = True

    recorder: WorkflowEventRecorder
    execution_id: str
    trace_context: TraceContext | None = None

    @property
    def authority_key(self) -> tuple[str, int]:
        emitter = getattr(self.recorder, "emitter", None)
        runtime = getattr(emitter, "runtime", None)
        if runtime is None:
            runtime = self.recorder
        return ("workflow_event_runtime", id(runtime))

    def rejected(
        self,
        *,
        operation_id: str,
        operation_kind: str,
        idempotency_key: str,
        admission: AdmissionResult,
    ) -> None:
        self.recorder.emit(
            "attempt_admission_rejected",
            attempt_rejection_event_payload(
                execution_id=self.execution_id,
                operation_id=operation_id,
                operation_kind=operation_kind,
                idempotency_key=idempotency_key,
                reason_code=(
                    admission.reason_code or "attempt_admission_rejected"
                ),
                admission=admission,
            ),
            trace_context=self.trace_context,
            component="framework.attempts",
        )

    def started(self, *, context: AttemptContext) -> None:
        self.recorder.emit(
            "attempt_started",
            attempt_started_event_payload(
                execution_id=self.execution_id,
                context=context,
            ),
            trace_context=self.trace_context,
            component="framework.attempts",
        )

    def terminal(self, *, outcome: AttemptOutcome[object]) -> None:
        context = outcome.context
        if context is None:
            raise RuntimeError("terminal attempt outcome is missing context")
        self.recorder.emit(
            "attempt_terminal",
            attempt_terminal_event_payload(
                execution_id=self.execution_id,
                context=context,
                state=_terminal_state(outcome),
                reason_code=_reason_code(outcome),
                termination_confirmed=outcome.termination_confirmed,
                indeterminate=outcome.indeterminate,
                elapsed_seconds=outcome.elapsed_seconds,
            ),
            trace_context=self.trace_context,
            component="framework.attempts",
        )


def _terminal_state(outcome: AttemptOutcome[object]) -> str:
    if outcome.indeterminate or outcome.state is AttemptState.INDETERMINATE:
        return "INDETERMINATE"
    if outcome.state is AttemptState.SUCCEEDED:
        return "SUCCEEDED"
    if outcome.state is AttemptState.TIMED_OUT:
        return "TIMED_OUT"
    return "FAILED"


def _reason_code(outcome: AttemptOutcome[object]) -> str | None:
    if outcome.reason_code:
        return outcome.reason_code
    error = outcome.error
    if isinstance(error, RuntimeExecutionError):
        return error.code
    if error is not None:
        return type(error).__name__
    return None


__all__ = ["WorkflowDurableAttemptSink"]
