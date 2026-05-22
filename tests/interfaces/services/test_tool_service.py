from interfaces.services.tool_service import ToolApplicationService


def test_tool_service_lists_business_tool_catalog() -> None:
    result = ToolApplicationService().list_tools()
    payload = result.to_dict()
    tool_names = {tool["name"] for tool in payload["tools"]}

    assert result.registry_valid is True
    assert payload["tool_count"] > 0
    assert "report.validate" in tool_names


def test_tool_service_exports_schema_with_policy() -> None:
    result = ToolApplicationService().export_schema(
        allowed_tools=["report.validate", "web.search"],
        blocked_tools=["web.search"],
    )
    payload = result.to_dict()

    assert payload["agent_id"] == "cli"
    assert payload["tool_count"] == 1
    assert payload["tools"][0]["name"] == "report.validate"
