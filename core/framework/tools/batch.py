from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from core.framework.artifacts import ArtifactManager
from core.framework.tools.executor import ToolExecutor
from core.framework.tools.models import (
    ToolCall,
    ToolDefinitionError,
    ToolObservation,
    ToolPolicy,
    ToolResult,
    ToolStatus,
)
from core.framework.tools.registry import ToolRegistry
from core.framework.tools.secrets import SecretProvider


_READ_ONLY_SIDE_EFFECTS = {"", "none", "read_only"}


class ToolBatchExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        artifact_manager: ArtifactManager | None = None,
        run_id: str | None = None,
        secret_provider: SecretProvider | None = None,
        max_workers: int = 4,
    ) -> None:
        self._registry = registry
        self._artifact_manager = artifact_manager
        self._run_id = run_id
        self._secret_provider = secret_provider
        self._max_workers = max(1, max_workers)

    def execute_batch(
        self,
        calls: list[ToolCall],
        policy: ToolPolicy,
        *,
        mode: str = "best_effort",
    ) -> list[ToolObservation]:
        if not calls:
            return []
        if mode not in {"best_effort", "strict"}:
            raise ValueError(f"unsupported tool batch mode: {mode}")
        if len(calls) > _max_tool_calls_per_iteration(policy):
            return [
                _blocked_budget_observation(
                    call,
                    "tool batch exceeds max_tool_calls_per_iteration "
                    f"of {_max_tool_calls_per_iteration(policy)}",
                )
                for call in calls
            ]
        if mode == "best_effort" and self._can_execute_parallel(calls):
            return self._execute_parallel(calls, policy)
        return self._execute_serial(calls, policy, mode=mode)

    def _execute_parallel(self, calls: list[ToolCall], policy: ToolPolicy) -> list[ToolObservation]:
        results: list[ToolObservation | None] = [None] * len(calls)
        worker_count = min(self._max_workers, len(calls))
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="news-tool-batch",
        ) as pool:
            future_to_index = {
                pool.submit(self._execute_one, call, policy): index
                for index, call in enumerate(calls)
            }
            for future in as_completed(future_to_index):
                results[future_to_index[future]] = future.result()
        return [result for result in results if result is not None]

    def _execute_one(self, call: ToolCall, policy: ToolPolicy) -> ToolObservation:
        executor = ToolExecutor(
            self._registry,
            artifact_manager=self._artifact_manager,
            run_id=self._run_id,
            secret_provider=self._secret_provider,
        )
        return executor.execute(call, policy)

    def _execute_serial(
        self,
        calls: list[ToolCall],
        policy: ToolPolicy,
        *,
        mode: str,
    ) -> list[ToolObservation]:
        observations: list[ToolObservation] = []
        for call in calls:
            observation = self._execute_one(call, policy)
            observations.append(observation)
            if mode == "strict" and observation.status != ToolStatus.SUCCEEDED:
                break
        return observations

    def _can_execute_parallel(self, calls: list[ToolCall]) -> bool:
        for call in calls:
            try:
                definition = self._registry.get(call.tool_name).definition
            except ToolDefinitionError:
                return False
            if definition.is_dangerous:
                return False
            if not definition.concurrency_safe:
                return False
            if definition.side_effect not in _READ_ONLY_SIDE_EFFECTS:
                return False
        return True


def _max_tool_calls_per_iteration(policy: ToolPolicy) -> int:
    return max(0, int(policy.max_tool_calls_per_iteration))


def _blocked_budget_observation(call: ToolCall, message: str) -> ToolObservation:
    return ToolObservation(
        call=call,
        result=ToolResult(
            status=ToolStatus.BLOCKED,
            error_type="ToolPermissionError",
            error_message=message,
        ),
        elapsed_ms=0.0,
    )
