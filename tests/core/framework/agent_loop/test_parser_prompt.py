import pytest

from core.framework.agent_loop import AgentActionParser, AgentActionParserError, AgentSpec, PromptBuilder


def test_action_parser_parses_tool_call() -> None:
    action = AgentActionParser().parse(
        '{"action_type":"tool_call","tool_name":"memory.search","tool_args":{"query":"ai"}}'
    )

    assert action.action_type == "tool_call"
    assert action.tool_name == "memory.search"
    assert action.tool_args == {"query": "ai"}


def test_action_parser_parses_final_output() -> None:
    action = AgentActionParser().parse(
        '{"action_type":"final_output","output":{"analysis_result":{"summary":"ok"}}}'
    )

    assert action.action_type == "final_output"
    assert action.output == {"analysis_result": {"summary": "ok"}}


def test_action_parser_parses_delegate_to_subagent() -> None:
    action = AgentActionParser().parse(
        (
            '{"action_type":"delegate_to_subagent",'
            '"subagent_id":"citation_sanity_checker",'
            '"subagent_task":"check citations",'
            '"handoff_reason":"citation risk"}'
        )
    )

    assert action.action_type == "delegate_to_subagent"
    assert action.subagent_id == "citation_sanity_checker"
    assert action.subagent_task == "check citations"
    assert action.handoff_reason == "citation risk"


def test_action_parser_rejects_invalid_json() -> None:
    with pytest.raises(AgentActionParserError, match="not valid JSON"):
        AgentActionParser().parse("not-json")


def test_prompt_builder_includes_inputs_feedback_and_observations() -> None:
    agent = AgentSpec(
        agent_id="analyst",
        name="Analyst",
        role="Analyze evidence",
        goal="Produce analysis",
        instructions="Return JSON actions only.",
        input_keys=["request"],
        output_key="analysis_result",
    )

    request = PromptBuilder().build(
        agent,
        {"request": {"topic": "chips"}},
        feedback="missing analysis_result",
        tool_observations=[{"tool_name": "memory.search", "status": "succeeded"}],
        tools=[{"name": "memory.search"}],
    )

    assert request.messages[0]["content"].startswith("Analyze evidence")
    assert "chips" in request.messages[1]["content"]
    assert "missing analysis_result" in request.messages[1]["content"]
    assert request.tools == [{"name": "memory.search"}]
