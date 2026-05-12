from core.framework.tools import ToolPolicy, audit_agent_tool_boundary


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
