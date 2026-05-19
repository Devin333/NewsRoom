import pytest

from core.framework.agent_loop import AgentLoopPolicy, AgentSpec
from core.framework.tools.models import ToolPolicy


def _agent(**kwargs) -> AgentSpec:
    defaults = {
        "agent_id": "analyst",
        "name": "Analyst",
        "role": "Analyze",
        "goal": "Return analysis",
        "instructions": "Return JSON",
        "input_keys": ["request"],
        "output_key": "analysis_result",
        "allowed_tools": ["memory.search"],
    }
    defaults.update(kwargs)
    return AgentSpec(**defaults)


def test_agent_spec_requires_agent_id() -> None:
    with pytest.raises(ValueError, match="agent_id is required"):
        _agent(agent_id="")


def test_agent_spec_contract_exports_and_imports_stably() -> None:
    spec = _agent(
        output_schema={
            "type": "object",
            "required": ["analysis_result"],
        },
        loop_policy=AgentLoopPolicy(max_iterations=3, allow_subagents=True),
        tool_policy=ToolPolicy(allowed_tools=["memory.search"], max_tool_calls_per_agent=4),
        model_policy={"provider": "fake", "model": "fake-llm"},
        validation_policy={"boundary": "input_only"},
        allowed_references=["input://request/a"],
        allowed_subagents=["citation_sanity_checker"],
        metadata={"version": "v1"},
    )

    restored = AgentSpec.from_dict(spec.to_dict())

    assert restored.to_dict() == spec.to_dict()
    assert restored.allow_subagents is True
    assert restored.allows_subagent("citation_sanity_checker") is True
    assert restored.allows_subagent("other_agent") is False


def test_agent_spec_defaults_subagent_delegation_off() -> None:
    spec = _agent(allowed_subagents=["citation_sanity_checker"])

    assert spec.allow_subagents is False
    assert spec.allows_subagent("citation_sanity_checker") is False


def test_restricted_writer_policy_removes_external_fetch_tools() -> None:
    spec = _agent(
        agent_id="writer",
        allowed_tools=["source.fetch_url", "web.search", "memory.search"],
    )
    policy = spec.resolved_tool_policy()

    assert policy.allows("memory.search") is True
    assert policy.allows("source.fetch_url") is False
    assert policy.allows("web.search") is False
    assert "source.fetch_url" in policy.blocked_tools


def test_restricted_editor_policy_removes_source_and_publish_tools() -> None:
    spec = _agent(
        agent_id="editor",
        allowed_tools=["source.add_manual", "report.publish", "quality.check_citations"],
    )
    policy = spec.resolved_tool_policy()

    assert policy.allows("quality.check_citations") is True
    assert policy.allows("source.add_manual") is False
    assert policy.allows("report.publish") is False
    assert "source.add_manual" in policy.blocked_tools
    assert "report.publish" in policy.blocked_tools
