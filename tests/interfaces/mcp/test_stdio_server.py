import io
import json

from interfaces.mcp.stdio_server import handle_jsonrpc_request, run_stdio
from interfaces.services.artifact_service import ArtifactInspectionService
from interfaces.services.mcp_service import MCPApplicationService
from interfaces.services.run_inspection_service import RunInspectionService
from tests.fixtures.workflow_runs import write_canonical_terminal_run


def test_stdio_handles_tools_list() -> None:
    response = handle_jsonrpc_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    assert response["id"] == 1
    tool_names = [tool["name"] for tool in response["result"]["tools"]]
    assert "news.research.analyze_paper" in tool_names
    assert "news.approval.submit" in tool_names
    assert "news.worker.status" in tool_names
    assert "news.queue.status" in tool_names


def test_stdio_handles_capabilities_list() -> None:
    response = handle_jsonrpc_request(
        {"jsonrpc": "2.0", "id": "cap-1", "method": "capabilities/list"}
    )

    assert response["id"] == "cap-1"
    assert response["result"]["version"] == "1.0"
    assert response["result"]["schema_version"] == "newsroom.mcp_capability_manifest.v1"
    assert response["result"]["boundary"] == "inbound_mcp_server"
    capabilities = {capability["name"]: capability for capability in response["result"]["capabilities"]}
    assert capabilities["news.report.latest"]["permission"] == "read:reports"
    assert capabilities["news.report.latest"]["read_only"] is True
    assert capabilities["news.report.latest"]["category"] == "reports"
    assert capabilities["news.report.latest"]["boundary"] == "inbound_mcp_server"
    assert capabilities["news.report.publish"]["requires_approval"] is True
    assert capabilities["news://reports/latest"]["kind"] == "resource"
    assert capabilities["news://reports/latest"]["permission"] == "read:reports"
    assert capabilities["news.evidence_audit"]["kind"] == "prompt"


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


def test_stdio_handles_resource_read() -> None:
    service = _FakeMCPService()

    response = handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": "read-1",
            "method": "resources/read",
            "params": {"uri": "news://sources/health"},
        },
        service=service,
    )

    assert service.resource_reads == ["news://sources/health"]
    assert response["result"]["success"] is True
    assert response["result"]["data"]["source_count"] == 1


def test_stdio_handles_run_replay_resource_read() -> None:
    service = _FakeMCPService()

    response = handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": "read-replay",
            "method": "resources/read",
            "params": {"uri": "news://runs/run-1/replay"},
        },
        service=service,
    )

    assert service.resource_reads == ["news://runs/run-1/replay"]
    assert response["result"]["success"] is True
    assert response["result"]["data"]["run_id"] == "run-1"


def test_stdio_preserves_typed_artifact_integrity_failure_envelopes() -> None:
    for error_type in [
        "ArtifactChecksumMismatchError",
        "ArtifactStoreMetadataError",
        "ArtifactStoreRequiredError",
    ]:
        service = _FailedMCPService(error_type)
        tool_response = handle_jsonrpc_request(
            {
                "jsonrpc": "2.0",
                "id": "call-replay",
                "method": "tools/call",
                "params": {"name": "news.run.replay", "arguments": {"run_id": "run-1"}},
            },
            service=service,
        )
        resource_response = handle_jsonrpc_request(
            {
                "jsonrpc": "2.0",
                "id": "read-artifact",
                "method": "resources/read",
                "params": {"uri": "news://runs/run-1/artifacts/output"},
            },
            service=service,
        )

        for response in [tool_response, resource_response]:
            result = response["result"]
            assert result["success"] is False
            assert result["data"] is None
            assert result["error_type"] == error_type
            assert result["error_message"] == "artifact integrity verification failed"


def test_stdio_real_filesystem_integrity_failure_has_no_tampered_data(tmp_path) -> None:
    fixture = write_canonical_terminal_run(tmp_path)
    fixture.artifact_path("output").write_text(
        '{"result":"tampered-stdio-secret"}',
        encoding="utf-8",
    )
    service = MCPApplicationService(
        run_inspection_service_factory=lambda: RunInspectionService(tmp_path),
        artifact_service_factory=lambda: ArtifactInspectionService(tmp_path),
    )
    requests = [
        {
            "jsonrpc": "2.0",
            "id": "real-tool-tamper",
            "method": "tools/call",
            "params": {"name": "news.run.replay", "arguments": {"run_id": "run-1"}},
        },
        {
            "jsonrpc": "2.0",
            "id": "real-resource-tamper",
            "method": "resources/read",
            "params": {"uri": "news://runs/run-1/artifacts/output"},
        },
    ]

    for request in requests:
        response = handle_jsonrpc_request(request, service=service)
        result = response["result"]
        assert result["success"] is False
        assert result["data"] is None
        assert result["error_type"] == "ArtifactChecksumMismatchError"
        assert "tampered-stdio-secret" not in json.dumps(response)


def test_stdio_handles_run_lineage_resource_read() -> None:
    service = _FakeMCPService()

    response = handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": "read-lineage",
            "method": "resources/read",
            "params": {"uri": "news://runs/run-1/lineage/upstream/evidence/ev-1"},
        },
        service=service,
    )

    assert service.resource_reads == ["news://runs/run-1/lineage/upstream/evidence/ev-1"]
    assert response["result"]["success"] is True
    assert response["result"]["data"]["lineage_count"] == 1


def test_stdio_handles_storage_metrics_resource_read() -> None:
    service = _FakeMCPService()

    response = handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": "read-storage",
            "method": "resources/read",
            "params": {"uri": "news://storage/metrics"},
        },
        service=service,
    )

    assert service.resource_reads == ["news://storage/metrics"]
    assert response["result"]["success"] is True
    assert response["result"]["data"]["runs_count"] == 1


def test_stdio_handles_storage_retention_plan_resource_read() -> None:
    service = _FakeMCPService()

    response = handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": "read-retention",
            "method": "resources/read",
            "params": {"uri": "news://storage/retention/plan"},
        },
        service=service,
    )

    assert service.resource_reads == ["news://storage/retention/plan"]
    assert response["result"]["success"] is True
    assert response["result"]["data"]["delete_count"] == 1


def test_stdio_handles_worker_status_resource_read() -> None:
    service = _FakeMCPService()

    response = handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": "read-workers",
            "method": "resources/read",
            "params": {"uri": "news://workers/worker-1"},
        },
        service=service,
    )

    assert service.resource_reads == ["news://workers/worker-1"]
    assert response["result"]["success"] is True
    assert response["result"]["data"]["worker_count"] == 1


def test_stdio_handles_queue_status_resource_read() -> None:
    service = _FakeMCPService()

    response = handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": "read-queues",
            "method": "resources/read",
            "params": {"uri": "news://queues"},
        },
        service=service,
    )

    assert service.resource_reads == ["news://queues"]
    assert response["result"]["success"] is True
    assert response["result"]["data"]["queue_count"] == 1


def test_stdio_handles_prompt_get() -> None:
    service = _FakeMCPService()

    response = handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": "prompt-1",
            "method": "prompts/get",
            "params": {"name": "news.evidence_audit", "arguments": {"run_id": "run-1"}},
        },
        service=service,
    )

    assert service.prompt_gets == [("news.evidence_audit", {"run_id": "run-1"})]
    assert response["result"]["success"] is True
    assert "run-1" in response["result"]["messages"][0]["content"]


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
        self.resource_reads = []
        self.prompt_gets = []

    def catalog(self):
        raise AssertionError("catalog should not be called")

    def call_tool(self, tool_name, arguments):
        self.calls.append((tool_name, arguments))
        return _FakeToolResult(tool_name)

    def read_resource(self, uri):
        self.resource_reads.append(uri)
        return _FakeResourceResult(uri)

    def get_prompt(self, name, arguments):
        self.prompt_gets.append((name, arguments))
        return _FakePromptResult(name, arguments)


class _FailedMCPService:
    def __init__(self, error_type) -> None:
        self.error_type = error_type

    def call_tool(self, tool_name, arguments):
        return _FailedToolResult(tool_name, self.error_type)

    def read_resource(self, uri):
        return _FailedResourceResult(uri, self.error_type)


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


class _FakeResourceResult:
    def __init__(self, uri) -> None:
        self.uri = uri

    def to_dict(self):
        return {
            "uri": self.uri,
            "success": True,
            "mime_type": "application/json",
            "data": _resource_payload(self.uri),
            "error_type": None,
            "error_message": None,
        }


class _FailedToolResult:
    def __init__(self, tool_name, error_type) -> None:
        self.tool_name = tool_name
        self.error_type = error_type

    def to_dict(self):
        return {
            "tool_name": self.tool_name,
            "success": False,
            "data": None,
            "error_type": self.error_type,
            "error_message": "artifact integrity verification failed",
        }


class _FailedResourceResult:
    def __init__(self, uri, error_type) -> None:
        self.uri = uri
        self.error_type = error_type

    def to_dict(self):
        return {
            "uri": self.uri,
            "success": False,
            "mime_type": "application/json",
            "data": None,
            "error_type": self.error_type,
            "error_message": "artifact integrity verification failed",
        }


class _FakePromptResult:
    def __init__(self, name, arguments) -> None:
        self.name = name
        self.arguments = arguments

    def to_dict(self):
        return {
            "name": self.name,
            "success": True,
            "description": "Prompt",
            "messages": [
                {
                    "role": "user",
                    "content": f"Audit {self.arguments.get('run_id')}",
                }
            ],
            "error_type": None,
            "error_message": None,
        }


def _resource_payload(uri):
    if uri.endswith("/replay"):
        return {"run_id": "run-1", "artifact_count": 0, "artifacts": []}
    if "/lineage" in uri:
        return {"run_id": "run-1", "lineage_count": 1, "lineage_refs": []}
    if uri == "news://storage/metrics":
        return {"runs_count": 1, "artifacts_count": 2}
    if uri == "news://storage/retention/plan":
        return {"artifact_count": 2, "delete_count": 1, "keep_count": 1}
    if uri.startswith("news://workers"):
        return {"worker_count": 1, "workers": [{"worker_id": "worker-1"}]}
    if uri == "news://queues":
        return {"queue_count": 1, "queues": [{"queue_name": "news:queue:memory"}]}
    return {"source_count": 1}
