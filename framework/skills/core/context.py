"""Skill run context models."""

from __future__ import annotations

from pydantic import BaseModel, Field
from framework.shared.graph_identity import GraphExecutionIdentity, GraphStageIdentity


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
    def for_standalone(cls, skill_name: str, run_id: str) -> "SkillRunContext":
        """Create an explicitly independent skill context without Graph authority."""
        return cls(run_id=run_id, skill_name=skill_name, caller_type="standalone")

    @classmethod
    def for_graph(
        cls,
        skill_name: str,
        graph_identity: GraphStageIdentity | GraphExecutionIdentity,
    ) -> "SkillRunContext":
        if not isinstance(graph_identity, (GraphStageIdentity, GraphExecutionIdentity)):
            raise TypeError("graph_identity must be a GraphStageIdentity or GraphExecutionIdentity")
        return cls(
            run_id=graph_identity.run_id,
            skill_name=skill_name,
            caller_type="graph",
            caller_id=graph_identity.node_instance_id,
            metadata={"graph_identity": graph_identity.to_dict()},
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
