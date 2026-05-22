"""Skill run context models."""

from __future__ import annotations

from pydantic import BaseModel, Field


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

    metadata: dict = Field(default_factory=dict)

    @classmethod
    def for_test(cls, skill_name: str, run_id: str = "test-run") -> "SkillRunContext":
        return cls(run_id=run_id, skill_name=skill_name, caller_type="test")

    @classmethod
    def for_workflow(cls, skill_name: str, workflow_run_id: str, step_id: str) -> "SkillRunContext":
        return cls(
            run_id=workflow_run_id,
            skill_name=skill_name,
            caller_type="workflow",
            caller_id=step_id,
            metadata={"workflow_run_id": workflow_run_id, "step_id": step_id},
        )

    @classmethod
    def for_agent(cls, skill_name: str, agent_run_id: str, call_id: str) -> "SkillRunContext":
        return cls(
            run_id=agent_run_id,
            skill_name=skill_name,
            caller_type="agent",
            caller_id=call_id,
            metadata={"agent_run_id": agent_run_id, "call_id": call_id},
        )
