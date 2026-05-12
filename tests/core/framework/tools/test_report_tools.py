from core.framework.tools import (
    ToolCall,
    ToolExecutor,
    ToolPolicy,
    ToolRegistry,
    ToolStatus,
    register_report_tools,
)


def test_report_tools_render_markdown_and_json_through_executor() -> None:
    registry = ToolRegistry()
    register_report_tools(registry)
    executor = ToolExecutor(registry)
    report = {
        "title": "Daily Report",
        "sections": [{"title": "Summary", "content": "All systems nominal."}],
        "source_urls": ["https://example.com/source"],
        "metadata": {"profile": "test"},
    }

    markdown_observation = executor.execute(
        ToolCall(tool_name="report.render_markdown", arguments={"report": report}),
        ToolPolicy(allowed_tools=["report.render_markdown"]),
    )
    json_observation = executor.execute(
        ToolCall(tool_name="report.render_json", arguments={"report": report}),
        ToolPolicy(allowed_tools=["report.render_json"]),
    )

    assert markdown_observation.status == ToolStatus.SUCCEEDED
    assert "# Daily Report" in markdown_observation.result.output["markdown"]
    assert "- https://example.com/source" in markdown_observation.result.output["markdown"]
    assert json_observation.status == ToolStatus.SUCCEEDED
    assert json_observation.result.output["report"]["title"] == "Daily Report"
    assert json_observation.result.output["report"]["metadata"] == {"profile": "test"}


def test_report_tool_rejects_invalid_report_payload() -> None:
    registry = ToolRegistry()
    register_report_tools(registry)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(tool_name="report.render_markdown", arguments={"report": {"sections": []}}),
        ToolPolicy(allowed_tools=["report.render_markdown"]),
    )

    assert observation.status == ToolStatus.FAILED
    assert observation.result.error_type == "ValueError"
    assert "report.title is required" in (observation.result.error_message or "")


def test_report_validate_tool_returns_structured_valid_result() -> None:
    registry = ToolRegistry()
    register_report_tools(registry)
    executor = ToolExecutor(registry)
    report = {
        "title": "Daily Report",
        "sections": [{"title": "Summary", "content": "All systems nominal."}],
        "source_urls": ["https://example.com/source"],
        "metadata": {"profile": "test"},
    }

    observation = executor.execute(
        ToolCall(tool_name="report.validate", arguments={"report": report}),
        ToolPolicy(allowed_tools=["report.validate"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output == {
        "valid": True,
        "errors": [],
        "section_count": 1,
        "source_url_count": 1,
    }


def test_report_validate_tool_returns_structured_errors_for_invalid_report() -> None:
    registry = ToolRegistry()
    register_report_tools(registry)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(tool_name="report.validate", arguments={"report": {"sections": []}}),
        ToolPolicy(allowed_tools=["report.validate"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["valid"] is False
    assert observation.result.output["errors"] == ["report.title is required"]
