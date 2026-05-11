import io
import json

from interfaces.mcp.stdio_server import handle_jsonrpc_request, run_stdio


def test_stdio_handles_tools_list() -> None:
    response = handle_jsonrpc_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    assert response["id"] == 1
    tool_names = [tool["name"] for tool in response["result"]["tools"]]
    assert tool_names[0] == "news.daily.enqueue"
    assert "news.approval.submit" in tool_names


def test_stdio_handles_tool_call() -> None:
    service = _FakeMCPService()

    response = handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": "call-1",
            "method": "tools/call",
            "params": {"name": "news.source.health", "arguments": {"include_disabled": True}},
        },
        service=service,
    )

    assert service.calls == [("news.source.health", {"include_disabled": True})]
    assert response["result"]["success"] is True
    assert response["result"]["data"]["source_count"] == 1


def test_stdio_unknown_method_returns_jsonrpc_error() -> None:
    response = handle_jsonrpc_request({"jsonrpc": "2.0", "id": 7, "method": "unknown"})

    assert response["error"]["code"] == -32601


def test_stdio_loop_reads_and_writes_json_lines() -> None:
    input_stream = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}) + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "x"}})
        + "\n"
    )
    output_stream = io.StringIO()

    run_stdio(input_stream=input_stream, output_stream=output_stream, service=_FakeMCPService())

    responses = [json.loads(line) for line in output_stream.getvalue().splitlines()]
    assert responses[0]["result"]["serverInfo"]["name"] == "NewsRoom"
    assert responses[1]["result"]["tool_name"] == "x"


class _FakeMCPService:
    def __init__(self) -> None:
        self.calls = []

    def catalog(self):
        raise AssertionError("catalog should not be called")

    def call_tool(self, tool_name, arguments):
        self.calls.append((tool_name, arguments))
        return _FakeToolResult(tool_name)


class _FakeToolResult:
    def __init__(self, tool_name) -> None:
        self.tool_name = tool_name

    def to_dict(self):
        return {
            "tool_name": self.tool_name,
            "success": True,
            "data": {"source_count": 1},
            "error_type": None,
            "error_message": None,
        }
