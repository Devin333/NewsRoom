from __future__ import annotations

from framework.skills import SkillRunContext


def test_skill_run_context_factories() -> None:
    test_context = SkillRunContext.for_test("runnable-skill")
    workflow_context = SkillRunContext.for_workflow("runnable-skill", "wf-run", "step-1")
    agent_context = SkillRunContext.for_agent("runnable-skill", "agent-run", "call-1")

    assert test_context.run_id == "test-run"
    assert test_context.caller_type == "test"
    assert workflow_context.caller_type == "workflow"
    assert workflow_context.caller_id == "step-1"
    assert workflow_context.metadata == {"workflow_run_id": "wf-run", "step_id": "step-1"}
    assert agent_context.caller_type == "agent"
    assert agent_context.caller_id == "call-1"
    assert agent_context.metadata == {"agent_run_id": "agent-run", "call_id": "call-1"}
