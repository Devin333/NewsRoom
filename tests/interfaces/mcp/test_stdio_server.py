import io
import json

from interfaces.mcp.stdio_server import handle_jsonrpc_request, run_stdio
from interfaces.services.artifact_service import ArtifactInspectionService
from interfaces.services.mcp_service import MCPApplicationService
from interfaces.services.run_inspection_service import GraphRunInspectionService
from tests.fixtures.graph_runs import graph_index_reader, write_graph_terminal_run


def test_stdio_handles_tools_list() -> None:
    response = handle_jsonrpc_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    assert response["id"] == 1
    tool_names = [tool["name"] for tool in response["result"]["tools"]]
    assert "news.research.analyze_paper" in tool_names
    assert "news.graph.approval.decision" in tool_names
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


def test_stdio_preserves_safe_request_identity_for_typed_not_found_results() -> None:
    service = MCPApplicationService()
    requests = [
        (
            {
                "jsonrpc": "2.0",
                "id": "missing-tool",
                "method": "tools/call",
                "params": {"name": "news.unknown", "arguments": {}},
            },
            "tool_name",
            "news.unknown",
            "MCPToolNotFound",
        ),
        (
            {
                "jsonrpc": "2.0",
                "id": "missing-resource",
                "method": "resources/read",
                "params": {"uri": "news://unknown"},
            },
            "uri",
            "news://unknown",
            "MCPResourceNotFound",
        ),
        (
            {
                "jsonrpc": "2.0",
                "id": "missing-prompt",
                "method": "prompts/get",
                "params": {"name": "news.unknown", "arguments": {}},
            },
            "name",
            "news.unknown",
            "MCPPromptNotFound",
        ),
    ]

    for request, identifier_field, identifier, error_type in requests:
        response = handle_jsonrpc_request(request, service=service)
        result = response["result"]
        assert result["success"] is False
        assert result[identifier_field] == identifier
        assert result["error_type"] == error_type
        assert identifier in result["error_message"]


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
    replay_fixture = write_graph_terminal_run(tmp_path, "run-replay")
    artifact_fixture = write_graph_terminal_run(tmp_path, "run-artifact")
    replay_fixture.artifact_path("output").write_text(
        '{"result":"tampered-stdio-secret"}',
        encoding="utf-8",
    )
    artifact_fixture.artifact_path("output").write_text(
        '{"result":"tampered-stdio-secret"}',
        encoding="utf-8",
    )
    service = MCPApplicationService(
        graph_run_inspection_service_factory=lambda: GraphRunInspectionService(
            tmp_path,
            graph_index_reader=graph_index_reader(tmp_path),
        ),
        artifact_service_factory=lambda: ArtifactInspectionService(tmp_path),
    )
    requests = [
        {
            "jsonrpc": "2.0",
            "id": "real-tool-tamper",
            "method": "tools/call",
            "params": {
                "name": "news.run.replay",
                "arguments": {"run_id": "run-replay"},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": "real-resource-tamper",
            "method": "resources/read",
            "params": {"uri": "news://runs/run-artifact/artifacts/output"},
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


def test_stdio_sanitizes_unknown_service_exception_and_failed_result() -> None:
    secret = "Bearer super-secret-token"
    exception_response = handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": "explode",
            "method": "resources/read",
            "params": {"uri": "news://reports/latest"},
        },
        service=_ExplodingMCPService(secret),
    )
    failed_response = handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": "failed",
            "method": "tools/call",
            "params": {"name": "news.report.latest"},
        },
        service=_UnsafeFailedMCPService(secret),
    )

    assert exception_response["error"]["code"] == -32603
    assert exception_response["error"]["message"] == "internal error"
    assert exception_response["error"]["data"]["error_type"] == "MCPInternalError"
    assert exception_response["error"]["data"]["error_id"].startswith("err_")
    assert failed_response["result"]["error_type"] == "MCPInternalError"
    assert failed_response["result"]["error_message"] == "internal error"
    assert failed_response["result"]["error_id"].startswith("err_")
    assert secret not in json.dumps(exception_response)
    assert secret not in json.dumps(failed_response)


def test_stdio_preserves_fixed_durable_event_failure_contract() -> None:
    secret = "postgresql://operator:password@db.internal/news"
    response = handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": "event-store-unavailable",
            "method": "tools/call",
            "params": {"name": "news.event.dead_letters.list"},
        },
        service=_DurableEventFailedMCPService(secret),
    )

    assert response["result"] == {
        "success": False,
        "tool_name": "news.event.dead_letters.list",
        "data": None,
        "error_type": "EventStoreUnavailableError",
        "error_message": "event store is unavailable",
    }
    assert secret not in json.dumps(response)


def test_stdio_preserves_all_fixed_event_operator_failure_contracts() -> None:
    expected = {
        "EventAuthorizationError": "event operator action is not authorized",
        "EventOperationCapabilityUnavailableError": (
            "event operator capability is unavailable"
        ),
        "EventOperationNotFoundError": "event operator resource not found",
        "EventRuntimeError": "event runtime operation failed",
    }

    for error_type, error_message in expected.items():
        response = handle_jsonrpc_request(
            {
                "jsonrpc": "2.0",
                "id": error_type,
                "method": "tools/call",
                "params": {"name": "news.event.dead_letters.list"},
            },
            service=_FailedMCPService(error_type),
        )

        assert response["result"]["error_type"] == error_type
        assert response["result"]["error_message"] == error_message
        assert "error_id" not in response["result"]


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


class _ExplodingMCPService:
    def __init__(self, secret) -> None:
        self.secret = secret

    def read_resource(self, uri):
        raise RuntimeError(self.secret)


class _UnsafeFailedMCPService:
    def __init__(self, secret) -> None:
        self.secret = secret

    def call_tool(self, tool_name, arguments):
        return _UnsafeFailedResult(tool_name, self.secret)


class _DurableEventFailedMCPService:
    def __init__(self, secret) -> None:
        self.secret = secret

    def call_tool(self, tool_name, arguments):
        return _DurableEventFailedResult(tool_name, self.secret)


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


class _UnsafeFailedResult:
    def __init__(self, tool_name, secret) -> None:
        self.tool_name = tool_name
        self.secret = secret

    def to_dict(self):
        return {
            "tool_name": self.tool_name,
            "success": False,
            "data": {"secret": self.secret},
            "error_type": "DatabaseDriverError",
            "error_message": self.secret,
        }


class _DurableEventFailedResult:
    def __init__(self, tool_name, secret) -> None:
        self.tool_name = tool_name
        self.secret = secret

    def to_dict(self):
        return {
            "tool_name": self.tool_name,
            "success": False,
            "data": {"dsn": self.secret},
            "error_type": "EventStoreUnavailableError",
            "error_message": self.secret,
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
