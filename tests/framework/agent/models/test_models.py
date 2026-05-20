import pytest

from framework.agent.models import (
    AgentAction,
    AgentActionType,
    AgentLoopPolicy,
    AgentLoopResult,
    AgentLoopStatus,
    AgentSpec,
)


def test_agent_spec_prd_fields_map_to_legacy_runtime_fields() -> None:
    spec = AgentSpec(
        agent_id="analyst",
        name="Analyst",
        instructions="Return JSON",
        model_route="fast",
        tool_names=["memory.search"],
        max_iterations=3,
    )

    assert spec.role == "Analyst"
    assert spec.goal == "Return JSON"
    assert spec.allowed_tools == ["memory.search"]
    assert spec.loop_policy.max_iterations == 3
    assert spec.model_policy["route_id"] == "fast"
    assert AgentSpec.from_dict(spec.to_dict()).to_dict() == spec.to_dict()


def test_agent_policy_status_action_and_result_prd_helpers() -> None:
    policy = AgentLoopPolicy(max_iterations=4, max_tool_calls=2)
    assert AgentLoopPolicy.from_dict(policy.to_dict()).to_dict() == policy.to_dict()
    assert policy.validate() == []
    assert AgentLoopStatus.SUCCEEDED.is_terminal() is True

    final = AgentAction.final("done")
    tool_call = AgentAction.tool_call("memory.search", {"query": "ai"})
    assert final.is_final() is True
    assert final.to_dict()["action_type"] == AgentActionType.FINAL.value
    assert tool_call.is_tool_call() is True

    success = AgentLoopResult.success_result("analyst", {"answer": "ok"}, [final])
    failure = AgentLoopResult.failure_result("analyst", RuntimeError("boom"))
    assert success.success is True
    assert success.final_output == {"answer": "ok"}
    assert failure.success is False
    assert failure.to_dict()["error"]["message"] == "boom"


def test_agent_spec_rejects_empty_agent_id() -> None:
    with pytest.raises(ValueError, match="agent_id is required"):
        AgentSpec(agent_id="", name="bad", instructions="nope")
