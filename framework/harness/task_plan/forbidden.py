from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.workers.result import FORBIDDEN_WORKER_RESULT_KEYS


FORBIDDEN_CANDIDATE_FIELDS = frozenset(
    {
        "active_package",
        "active_skill",
        "active_version",
        "approval_decision",
        "approval_granted",
        "authorization",
        "authorization_decision",
        "authorize",
        "callable",
        "compensation",
        "complete_run",
        "function",
        "halt",
        "halt_workflow",
        "handler",
        "handler_ref",
        "hidden_prompt",
        "implementation",
        "implementation_ref",
        "join",
        "loop_exit",
        "memory_write",
        "memory_write_allowed",
        "memory_write_decision",
        "next_route",
        "next_step",
        "parent_raw_messages",
        "promote_skill",
        "publication",
        "publication_approved",
        "publication_decision",
        "publish",
        "publish_artifact",
        "quality_passed",
        "quality_score",
        "quality_verdict",
        "raw_prompt",
        "release_skill",
        "route",
        "route_to",
        "route_to_repair",
        "routing_decision",
        "side_effect",
        "side_effect_handler",
        "subagent_id",
        "subagent_ref",
        "tool_authorization",
        "tool_authorized",
        "tool_policy_ref",
        "winner",
        "worker_id",
        "worker_ref",
        "worker_version",
        "write_memory",
    }
    | FORBIDDEN_WORKER_RESULT_KEYS
)


def forbidden_candidate_paths(value: Any, *, path: str = "$") -> tuple[str, ...]:
    found: list[str] = []

    def visit(item: Any, current_path: str) -> None:
        if isinstance(item, Mapping):
            for raw_key, child in item.items():
                key = str(raw_key)
                normalized = key.casefold().replace("-", "_")
                child_path = f"{current_path}.{key}"
                if normalized in FORBIDDEN_CANDIDATE_FIELDS:
                    found.append(child_path)
                visit(child, child_path)
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            for index, child in enumerate(item):
                visit(child, f"{current_path}[{index}]")

    visit(value, path)
    return tuple(sorted(set(found)))


def ensure_candidate_only(value: Any, *, path: str = "$") -> None:
    forbidden_paths = forbidden_candidate_paths(value, path=path)
    if forbidden_paths:
        raise HarnessValidationError(
            "TaskPlan candidate contains executable control fields",
            code="task_plan_forbidden_candidate_field",
            details={
                "code": "task_plan_forbidden_candidate_field",
                "forbidden_paths": list(forbidden_paths),
            },
        )


__all__ = [
    "FORBIDDEN_CANDIDATE_FIELDS",
    "ensure_candidate_only",
    "forbidden_candidate_paths",
]
