from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import StrEnum
from typing import Any

from framework.tool.models import (
    ToolCall,
    ToolDefinitionError,
    ToolObservation,
    ToolPolicy,
    ToolResult,
    ToolStatus,
    is_default_dangerous_tool_name,
)
from framework.tool.registry.registry import ToolRegistry
from framework.tool.runtime.executor import ToolExecutor


_READ_ONLY_SIDE_EFFECTS = {"", "none", "read_only"}


class BatchCompletionMode(StrEnum):
    """Controls how the batch executor handles partial failures.

    BEST_EFFORT  – (default) run all tools regardless of failures; return all results.
    STRICT       – stop on first failure; attempt compensation for completed tools.
    ANY_SUCCESS  – succeed if at least one tool succeeds.
    QUORUM       – succeed if at least *quorum* tools succeed (set via execute_batch kwarg).
    """

    BEST_EFFORT = "best_effort"
    STRICT = "strict"
    ANY_SUCCESS = "any_success"
    QUORUM = "quorum"


class ToolBatchExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        artifact_manager: Any | None = None,
        run_id: str | None = None,
        secret_provider: Any | None = None,
        max_workers: int = 4,
        compensating_actions: dict[str, Callable[[ToolObservation], None]] | None = None,
    ) -> None:
        self._registry = registry
        self._artifact_manager = artifact_manager
        self._run_id = run_id
        self._secret_provider = secret_provider
        self._max_workers = max(1, max_workers)
        # Fix #5: registry of rollback callables keyed by tool name
        self._compensating_actions: dict[str, Callable[[ToolObservation], None]] = (
            compensating_actions or {}
        )

    def execute_batch(
        self,
        calls: list[ToolCall],
        policy: ToolPolicy | None = None,
        *,
        mode: str = "best_effort",
        max_workers: int | None = None,
        quorum: int | None = None,
    ) -> list[ToolObservation]:
        """Execute a batch of tool calls.

        Args:
            calls:      Tool calls to execute.
            policy:     Tool policy; defaults to permissive.
            mode:       One of BatchCompletionMode values.
            max_workers: Override instance-level thread pool size for this call.
            quorum:     Required successes for QUORUM mode.
        """
        policy = policy or ToolPolicy(require_explicit_allowlist=False)
        if not calls:
            return []
        if mode not in {m.value for m in BatchCompletionMode}:
            raise ValueError(f"unsupported tool batch mode: {mode}")

        # Budget guard: block entire batch upfront if over limit
        max_calls = _max_tool_calls_per_iteration(policy)
        if len(calls) > max_calls:
            return [
                _blocked_budget_observation(
                    call,
                    f"tool batch exceeds max_tool_calls_per_iteration of {max_calls}",
                )
                for call in calls
            ]

        if mode == BatchCompletionMode.STRICT:
            return self._execute_strict(calls, policy)

        # Fix #2: split into parallel-safe and unsafe instead of all-or-nothing
        safe_calls, unsafe_calls = self._split_by_parallelism(calls)
        results: list[ToolObservation] = []
        if safe_calls:
            results.extend(
                self._execute_parallel(safe_calls, policy, max_workers=max_workers)
            )
        if unsafe_calls:
            results.extend(self._execute_serial(unsafe_calls, policy))

        # Restore original call order
        order = {call.call_id: i for i, call in enumerate(calls)}
        results.sort(key=lambda obs: order.get(obs.call.call_id, len(calls)))

        # Fix #1: apply aggregation policy
        if mode == BatchCompletionMode.ANY_SUCCESS:
            if not any(obs.status == ToolStatus.SUCCEEDED for obs in results):
                return [_failed_aggregation_observation(c, "any_success: no tool succeeded") for c in calls]
        elif mode == BatchCompletionMode.QUORUM:
            required = max(1, int(quorum or 1))
            succeeded = sum(1 for obs in results if obs.status == ToolStatus.SUCCEEDED)
            if succeeded < required:
                return [
                    _failed_aggregation_observation(
                        c, f"quorum: only {succeeded}/{required} tools succeeded"
                    )
                    for c in calls
                ]
        return results

    # ── internal helpers ──────────────────────────────────────────────────────

    def _split_by_parallelism(
        self, calls: list[ToolCall]
    ) -> tuple[list[ToolCall], list[ToolCall]]:
        """Fix #2: separate concurrency-safe calls from side-effect calls."""
        safe: list[ToolCall] = []
        unsafe: list[ToolCall] = []
        for call in calls:
            try:
                definition = self._registry.get(call.tool_name).definition
                if (
                    not definition.is_dangerous
                    and not is_default_dangerous_tool_name(definition.name)
                    and definition.concurrency_safe
                    and definition.side_effect_value in _READ_ONLY_SIDE_EFFECTS
                ):
                    safe.append(call)
                else:
                    unsafe.append(call)
            except ToolDefinitionError:
                unsafe.append(call)
        return safe, unsafe

    def _execute_parallel(
        self,
        calls: list[ToolCall],
        policy: ToolPolicy,
        *,
        max_workers: int | None = None,
    ) -> list[ToolObservation]:
        results: list[ToolObservation | None] = [None] * len(calls)
        worker_count = min(max_workers or self._max_workers, len(calls))
        with ThreadPoolExecutor(
            max_workers=worker_count, thread_name_prefix="news-tool-batch"
        ) as pool:
            future_to_index = {
                pool.submit(self._execute_one, call, policy): idx
                for idx, call in enumerate(calls)
            }
            for future in as_completed(future_to_index):
                results[future_to_index[future]] = future.result()
        return [r for r in results if r is not None]

    def _execute_serial(
        self, calls: list[ToolCall], policy: ToolPolicy
    ) -> list[ToolObservation]:
        return [self._execute_one(call, policy) for call in calls]

    def _execute_strict(
        self, calls: list[ToolCall], policy: ToolPolicy
    ) -> list[ToolObservation]:
        """Fix #5: serial execution; compensate completed tools on first failure."""
        completed: list[ToolObservation] = []
        for call in calls:
            obs = self._execute_one(call, policy)
            completed.append(obs)
            if obs.status != ToolStatus.SUCCEEDED:
                self._compensate(completed[:-1])  # rollback all but the failed one
                break
        return completed

    def _compensate(self, observations: list[ToolObservation]) -> None:
        """Fix #5: run compensating actions in reverse order (best-effort)."""
        for obs in reversed(observations):
            action = self._compensating_actions.get(obs.call.tool_name)
            if action is not None:
                try:
                    action(obs)
                except Exception:  # noqa: BLE001
                    pass  # compensation is best-effort; log in production

    def _execute_one(self, call: ToolCall, policy: ToolPolicy) -> ToolObservation:
        executor = ToolExecutor(
            self._registry,
            artifact_manager=self._artifact_manager,
            run_id=self._run_id,
            secret_provider=self._secret_provider,
        )
        return executor.execute(call, policy)


def _max_tool_calls_per_iteration(policy: ToolPolicy) -> int:
    return max(0, int(policy.max_tool_calls_per_iteration))


def _blocked_budget_observation(call: ToolCall, message: str) -> ToolObservation:
    return ToolObservation(
        call=call,
        result=ToolResult(
            status=ToolStatus.BLOCKED,
            error_type="ToolPermissionError",
            error_message=message,
            call_id=call.call_id,
            tool_name=call.tool_name,
        ),
        elapsed_ms=0.0,
    )


def _failed_aggregation_observation(call: ToolCall, message: str) -> ToolObservation:
    """Fix #1: synthetic failure observation for unmet aggregation policy."""
    return ToolObservation(
        call=call,
        result=ToolResult(
            status=ToolStatus.FAILED,
            error_type="BatchAggregationError",
            error_message=message,
            call_id=call.call_id,
            tool_name=call.tool_name,
        ),
        elapsed_ms=0.0,
    )
