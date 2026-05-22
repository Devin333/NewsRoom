from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from framework.specs import WorkflowSpec
from framework.workflow import FunctionStepRegistry


@dataclass(frozen=True)
class ResolvedWorkflow:
    workflow: WorkflowSpec
    profile: str
    registry: FunctionStepRegistry


class RunResolutionApplicationService:
    def __init__(self, resolver: Callable[[str], ResolvedWorkflow] | None = None) -> None:
        self._resolver = resolver

    def resolve_approval_resume_workflow(
        self,
        workflow_id: str,
        *,
        profile: str | None,
    ) -> ResolvedWorkflow:
        if self._resolver is None:
            raise RuntimeError("approval resume workflow resolver is not configured")
        return self._resolver(workflow_id, profile=profile)


def resolve_approval_resume_workflow(
    workflow_id: str,
    *,
    profile: str | None,
) -> ResolvedWorkflow:
    raise RuntimeError("approval resume workflow resolver is not configured")


def normalize_workflow_id(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        raise ValueError("workflow_id is required")
    return normalized


def normalize_profile(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized or None


__all__ = [
    "ResolvedWorkflow",
    "RunResolutionApplicationService",
    "normalize_profile",
    "normalize_workflow_id",
    "resolve_approval_resume_workflow",
]
