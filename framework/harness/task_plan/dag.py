from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.task_plan.canonical import identifier, non_negative_int


def task_dependency_depths(
    dependencies_by_task: Mapping[str, Sequence[str]],
    *,
    max_depth: int | None = None,
) -> dict[str, int]:
    """Analyze one task DAG deterministically in O(V+E)."""

    dependencies = {
        identifier(task_id, "task_id"): tuple(
            identifier(dependency, "dependency") for dependency in task_dependencies
        )
        for task_id, task_dependencies in dependencies_by_task.items()
    }
    known = frozenset(dependencies)
    for task_id in sorted(dependencies):
        unknown = sorted(set(dependencies[task_id]) - known)
        if unknown:
            raise HarnessValidationError(
                "TaskPlan references an unknown dependency",
                code="task_plan_unknown_dependency",
                details={"task_id": task_id, "dependency": unknown[0]},
            )

    memo: dict[str, int] = {}
    visiting: set[str] = set()

    def visit(task_id: str) -> int:
        cached = memo.get(task_id)
        if cached is not None:
            return cached
        if task_id in visiting:
            raise HarnessValidationError(
                "TaskPlan dependency graph contains a cycle",
                code="task_plan_dependency_cycle",
                details={"task_id": task_id},
            )
        visiting.add(task_id)
        task_dependencies = dependencies[task_id]
        depth = (
            max(visit(dependency) for dependency in task_dependencies) + 1
            if task_dependencies
            else 0
        )
        visiting.remove(task_id)
        memo[task_id] = depth
        return depth

    for task_id in sorted(dependencies):
        visit(task_id)

    roots = tuple(sorted(task_id for task_id, values in dependencies.items() if not values))
    if dependencies and not roots:
        raise HarnessValidationError(
            "TaskPlan has no executable root task",
            code="task_plan_no_executable_root",
        )
    reverse: dict[str, list[str]] = {task_id: [] for task_id in dependencies}
    for task_id, task_dependencies in dependencies.items():
        for dependency in task_dependencies:
            reverse[dependency].append(task_id)
    reachable: set[str] = set()
    queue = deque(roots)
    while queue:
        task_id = queue.popleft()
        if task_id in reachable:
            continue
        reachable.add(task_id)
        queue.extend(sorted(reverse[task_id]))
    unreachable = sorted(known - reachable)
    if unreachable:
        raise HarnessValidationError(
            "TaskPlan contains a task unreachable from any root",
            code="task_plan_unreachable_task",
            details={"task_id": unreachable[0]},
        )

    if max_depth is not None:
        limit = non_negative_int(max_depth, "max_depth")
        exceeded = sorted(task_id for task_id, depth in memo.items() if depth > limit)
        if exceeded:
            task_id = exceeded[0]
            raise HarnessValidationError(
                "TaskPlan dependency depth exceeds policy",
                code="task_plan_depth_exceeded",
                details={"task_id": task_id, "depth": memo[task_id], "max_depth": limit},
            )
    return dict(sorted(memo.items()))


__all__ = ["task_dependency_depths"]
