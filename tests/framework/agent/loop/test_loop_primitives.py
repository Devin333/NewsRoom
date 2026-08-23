from framework.agent.loop import AgentActionParser, AgentPlanner, ObservationBuilder, TerminationController
from framework.agent.models import AgentAction, AgentLoopPolicy, AgentLoopStopReason
from framework.tool import ToolResult, ToolStatus


class _State:
    iteration = 8
    stalled = False
    last_action = None


def test_parser_supports_prd_action_shapes() -> None:
    parser = AgentActionParser()

    final = parser.parse_json_action({"action_type": "final", "content": "done"})
    delegate = parser.parse_json_action(
        {"action_type": "delegate", "agent_id": "critic", "task": "check"}
    )

    assert final.is_final() is True
    assert final.content == "done"
    assert delegate.subagent_id == "critic"
    assert delegate.subagent_task == "check"


def test_observation_planner_and_termination_primitives() -> None:
    observation = ObservationBuilder().from_tool_result(
        "memory.recall",
        ToolResult(status=ToolStatus.SUCCEEDED, output={"api_key": "secret"}),
    )
    should_stop, reason = TerminationController().should_stop(_State(), AgentLoopPolicy())
    plan = AgentPlanner().plan_next(_State())

    assert observation["result"]["output"]["api_key"] == "[redacted]"
    assert should_stop is True
    assert reason == AgentLoopStopReason.MAX_ITERATIONS
    assert plan["next"] == "continue"


def test_termination_detects_final_action() -> None:
    state = _State()
    state.iteration = 1
    state.last_action = AgentAction.final("done")

    should_stop, reason = TerminationController().should_stop(state, AgentLoopPolicy())

    assert should_stop is True
    assert reason == AgentLoopStopReason.FINAL_ANSWER
