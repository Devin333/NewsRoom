from core.framework.agent_loop import AgentSpec
from core.framework.tools import ToolPolicy, audit_agent_spec_tool_boundary, audit_agent_tool_boundary


def test_agent_tool_boundary_blocks_configured_agent_tools() -> None:
    report = audit_agent_tool_boundary(
        {
            "locked": ToolPolicy(allowed_tools=["http.fetch", "artifact.render"]),
            "reviewer": {"allowed_tools": ["web.search"]},
            "analyst": ["http.fetch"],
        },
        restricted_agent_ids={"locked", "reviewer"},
        external_fetch_tool_prefixes=("http.",),
        external_fetch_tool_names={"web.search"},
    )

    assert report.ok is False
    assert report.blocking_finding_count == 2
    assert [finding.tool_name for finding in report.findings] == ["http.fetch", "web.search"]
    assert report.to_dict()["findings"][0]["action"] == "remove_tool_from_agent_policy"


def test_agent_tool_boundary_allows_agent_without_configured_tools() -> None:
    report = audit_agent_tool_boundary(
        {
            "LockedAgent": ToolPolicy(allowed_tools=[]),
            "ReviewerAgent": {"allowed_tools": ["score.compute"]},
        },
        restricted_agent_ids={"lockedagent", "revieweragent"},
        external_fetch_tool_prefixes=("http.",),
    )

    assert report.ok is True
    assert report.finding_count == 0


def test_agent_spec_tool_boundary_contract_blocks_configured_allowlists() -> None:
    writer = AgentSpec(
        agent_id="LockedAgent",
        name="Locked",
        role="Process",
        goal="Process inputs",
        instructions="Use approved inputs only.",
        input_keys=["approved_inputs"],
        output_key="draft_output",
        allowed_tools=["artifact.render_markdown", "web.search"],
    )
    editor = AgentSpec(
        agent_id="ReviewerAgent",
        name="Reviewer",
        role="Review",
        goal="Review output quality",
        instructions="Use provided inputs only.",
        input_keys=["draft_output", "input_bundle"],
        output_key="review_result",
        tool_policy=ToolPolicy(allowed_tools=["score.compute", "http.fetch"]),
    )

    report = audit_agent_spec_tool_boundary(
        [writer, editor],
        restricted_agent_ids={"lockedagent", "revieweragent"},
        external_fetch_tool_prefixes=("http.",),
        external_fetch_tool_names={"web.search"},
    )

    assert report.ok is False
    assert report.blocking_finding_count == 2
    assert [(finding.agent_id, finding.tool_name) for finding in report.findings] == [
        ("LockedAgent", "web.search"),
        ("ReviewerAgent", "http.fetch"),
    ]
