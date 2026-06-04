from __future__ import annotations

from framework.harness import SubAgentToolAllowlistGate, fake_subagent_spec


def test_subagent_cannot_inherit_sibling_tool_allowlist() -> None:
    verifier = fake_subagent_spec(subagent_id="verifier", allowed_tools=("search.read",))
    result = SubAgentToolAllowlistGate().evaluate(verifier, ("artifact.write",))

    assert result.passed is False
    assert result.details["denied"] == ["artifact.write"]


def test_authorized_tool_call_passes() -> None:
    verifier = fake_subagent_spec(subagent_id="verifier", allowed_tools=("search.read",))
    result = SubAgentToolAllowlistGate().evaluate(verifier, ("search.read",))

    assert result.passed is True
