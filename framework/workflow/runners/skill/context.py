from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field

try:  # pragma: no cover - exercised when framework.skills is present.
    from framework.skills.context import SkillRunContext as SkillRunContext
except ModuleNotFoundError:  # pragma: no cover - fallback is covered through behavior.

    class SkillRunContext(BaseModel):
        run_id: str = Field(min_length=1)
        skill_name: str = Field(min_length=1)
        caller_type: str = "unknown"
        caller_id: str | None = None
        trace_id: str | None = None
        memory_scope: str | None = None
        dry_run: bool = False
        timeout_seconds: int | None = None
        max_retries: int = 0
        metadata: dict[str, Any] = Field(default_factory=dict)

        @classmethod
        def for_workflow(
            cls,
            skill_name: str,
            workflow_run_id: str,
            step_id: str,
        ) -> "SkillRunContext":
            return cls(
                run_id=workflow_run_id,
                skill_name=skill_name,
                caller_type="workflow",
                caller_id=workflow_run_id,
                metadata={
                    "workflow_run_id": workflow_run_id,
                    "step_id": step_id,
                },
            )


class SkillRunnerProtocol(Protocol):
    def run(
        self,
        skill_name: str,
        input_data: dict[str, Any],
        context: SkillRunContext | None = None,
    ) -> Any:
        ...


__all__ = [
    "SkillRunContext",
    "SkillRunnerProtocol",
]
