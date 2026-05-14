from core.framework.agent_loop import AgentSpec
from core.framework.tools import ToolPolicy, audit_agent_spec_tool_boundary, audit_agent_tool_boundary


def test_agent_tool_boundary_blocks_writer_external_fetch_tools() -> None:
    report = audit_agent_tool_boundary(
        {
            "writer": ToolPolicy(allowed_tools=["source.fetch_url", "report.render"]),
            "editor": {"allowed_tools": ["web.search"]},
            "analyst": ["source.fetch_url"],
        }
    )

    assert report.ok is False
    assert report.blocking_finding_count == 2
    assert [finding.tool_name for finding in report.findings] == ["source.fetch_url", "web.search"]
    assert report.to_dict()["findings"][0]["action"] == "remove_tool_from_agent_policy"


def test_agent_tool_boundary_allows_writer_without_external_tools() -> None:
    report = audit_agent_tool_boundary(
        {
            "WriterAgent": ToolPolicy(allowed_tools=[]),
            "EditorAgent": {"allowed_tools": ["quality.editor_score"]},
        }
    )

    assert report.ok is True
    assert report.finding_count == 0


def test_agent_spec_tool_boundary_contract_blocks_writer_and_editor_fetch_allowlists() -> None:
    writer = AgentSpec(
        agent_id="WriterAgent",
        name="Writer",
        role="Draft reports",
        goal="Write a report",
        instructions="Use verified inputs only.",
        input_keys=["verified_findings"],
        output_key="draft_report",
        allowed_tools=["report.render_markdown", "web.search"],
    )
    editor = AgentSpec(
        agent_id="EditorAgent",
        name="Editor",
        role="Review reports",
        goal="Review report quality",
        instructions="Use provided evidence only.",
        input_keys=["draft_report", "evidence_bundle"],
        output_key="editor_review",
        tool_policy=ToolPolicy(allowed_tools=["quality.editor_score", "source.fetch_url"]),
    )

    report = audit_agent_spec_tool_boundary([writer, editor])

    assert report.ok is False
    assert report.blocking_finding_count == 2
    assert [(finding.agent_id, finding.tool_name) for finding in report.findings] == [
        ("WriterAgent", "web.search"),
        ("EditorAgent", "source.fetch_url"),
    ]
