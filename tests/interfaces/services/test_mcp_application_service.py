import json

from interfaces.services.approval_service import ApprovalApplicationService
from interfaces.services.mcp_service import MCPApplicationService
from interfaces.services.report_service import ReportApplicationService


def test_mcp_catalog_lists_tools_without_calling_factories() -> None:
    service = MCPApplicationService(
        worker_service_factory=_raising_factory,
        report_service_factory=_raising_factory,
        source_service_factory=_raising_factory,
        memory_service_factory=_raising_factory,
        diagnostic_service_factory=_raising_factory,
        approval_service_factory=_raising_factory,
    )

    catalog = service.catalog().to_dict()
    tool_names = [tool["name"] for tool in catalog["tools"]]

    assert "news.daily.enqueue" in tool_names
    assert "news.approval.submit" in tool_names
    assert "news://reports/latest" in [resource["uri"] for resource in catalog["resources"]]
    assert "news.evidence_audit" in [prompt["name"] for prompt in catalog["prompts"]]


def test_mcp_source_health_tool_calls_source_service() -> None:
    service = MCPApplicationService(source_service_factory=lambda: _FakeSourceService())

    result = service.call_tool("news.source.health", {"include_disabled": True})

    assert result.success is True
    assert result.to_dict()["data"]["health"][0]["source_id"] == "source-1"


def test_mcp_unknown_tool_fails_safely() -> None:
    service = MCPApplicationService()

    result = service.call_tool("news.unknown")

    assert result.success is False
    assert result.error_type == "MCPToolNotFound"


def test_mcp_memory_search_requires_query() -> None:
    service = MCPApplicationService(memory_service_factory=lambda: _FakeMemoryService())

    result = service.call_tool("news.memory.search", {})

    assert result.success is False
    assert result.error_type == "ValueError"
    assert "query is required" in result.error_message


def test_mcp_approval_tools_persist_submit_approve_and_read(tmp_path) -> None:
    store_path = tmp_path / "approvals.json"
    service = MCPApplicationService(
        approval_service_factory=lambda: ApprovalApplicationService(store_path=store_path)
    )

    submitted = service.call_tool(
        "news.approval.submit",
        {
            "requested_action": "publish_report",
            "risk_level": "high",
            "reason": "operator review required",
            "payload": {"report_id": "report-1"},
            "run_id": "run-1",
            "requested_by": "worker",
        },
    )

    assert submitted.success is True
    approval_id = submitted.data["approval_id"]
    assert submitted.data["approval"]["status"] == "pending"

    approved = service.call_tool(
        "news.approval.approve",
        {"approval_id": approval_id, "decided_by": "operator", "reason": "ready"},
    )
    fetched = service.call_tool("news.approval.get", {"approval_id": approval_id})
    listed = service.call_tool("news.approval.list", {"status": "approved"})

    assert store_path.exists()
    assert approved.success is True
    assert approved.data["approval"]["status"] == "approved"
    assert approved.data["approval"]["decision"]["decided_by"] == "operator"
    assert fetched.data["approval"]["status"] == "approved"
    assert listed.data["approval_count"] == 1
    assert listed.data["approvals"][0]["approval_id"] == approval_id


def test_mcp_reads_latest_report_resource_from_local_json_artifact(tmp_path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    report_json = run_dir / "report.json"
    report_markdown = run_dir / "report.md"
    report_json.write_text(json.dumps({"title": "Daily Intelligence"}), encoding="utf-8")
    report_markdown.write_text("# Daily Intelligence", encoding="utf-8")
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "status": "succeeded",
                "finished_at": "2026-05-11T01:00:00Z",
                "artifacts": {
                    "report_json": "report.json",
                    "report_markdown": "report.md",
                },
            }
        ),
        encoding="utf-8",
    )
    service = MCPApplicationService(
        report_service_factory=lambda: ReportApplicationService(artifact_root=tmp_path)
    )

    result = service.read_resource("news://reports/latest")

    assert result.success is True
    assert result.data["run_id"] == "run-1"
    assert result.data["report_json"] == {"title": "Daily Intelligence"}
    assert result.data["report_markdown"] == "# Daily Intelligence"


def test_mcp_unknown_resource_fails_safely() -> None:
    result = MCPApplicationService().read_resource("news://missing")

    assert result.success is False
    assert result.error_type == "MCPResourceNotFound"


def _raising_factory():
    raise AssertionError("factory should not be called")


class _FakeSourceService:
    def source_health(self, *, enabled_only):
        return _FakeResult(
            {
                "source_count": 1,
                "health": [
                    {
                        "source_id": "source-1",
                        "status": "healthy",
                        "consecutive_failures": 0,
                        "last_success_at": None,
                        "last_failure_at": None,
                        "cooldown_until": None,
                        "last_error": None,
                    }
                ],
            }
        )


class _FakeMemoryService:
    def search(self, **kwargs):
        return _FakeResult({"result_count": 0, "results": []})


class _FakeResult:
    def __init__(self, payload) -> None:
        self.payload = payload

    def to_dict(self):
        return self.payload
