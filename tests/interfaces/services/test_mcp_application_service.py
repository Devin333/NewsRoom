import json

from interfaces.services.approval_service import ApprovalApplicationService
from interfaces.services.artifact_service import ArtifactInspectionService
from interfaces.services.mcp_service import MCPApplicationService
from interfaces.services.report_service import ReportApplicationService
from interfaces.services.run_inspection_service import RunInspectionService


def test_mcp_catalog_lists_tools_without_calling_factories() -> None:
    service = MCPApplicationService(
        worker_service_factory=_raising_factory,
        report_service_factory=_raising_factory,
        source_service_factory=_raising_factory,
        memory_service_factory=_raising_factory,
        diagnostic_service_factory=_raising_factory,
        approval_service_factory=_raising_factory,
        run_inspection_service_factory=_raising_factory,
        artifact_service_factory=_raising_factory,
    )

    catalog = service.catalog().to_dict()
    tool_names = [tool["name"] for tool in catalog["tools"]]
    resource_uris = [resource["uri"] for resource in catalog["resources"]]

    assert "news.daily.enqueue" in tool_names
    assert "news.report.search" in tool_names
    assert "news.run.show" in tool_names
    assert "news.run.events" in tool_names
    assert "news.approval.submit" in tool_names
    assert "news://reports/latest" in resource_uris
    assert "news://reports/{report_id}" in resource_uris
    assert "news://runs/{run_id}/manifest" in resource_uris
    assert "news://runs/{run_id}/events" in resource_uris
    assert "news://runs/{run_id}/artifacts/{artifact_key}" in resource_uris
    prompt_names = [prompt["name"] for prompt in catalog["prompts"]]
    assert "news.evidence_audit" in prompt_names
    assert "news.quality_gate_explain" in prompt_names
    assert "news.trend_analysis_prompt" in prompt_names


def test_mcp_source_health_tool_calls_source_service() -> None:
    service = MCPApplicationService(source_service_factory=lambda: _FakeSourceService())

    result = service.call_tool("news.source.health", {"include_disabled": True})

    assert result.success is True
    assert result.to_dict()["data"]["health"][0]["source_id"] == "source-1"


def test_mcp_get_prompt_renders_arguments() -> None:
    service = MCPApplicationService()

    result = service.get_prompt("news.evidence_audit", {"run_id": "run-1"})

    assert result.success is True
    payload = result.to_dict()
    assert payload["name"] == "news.evidence_audit"
    assert "run-1" in payload["messages"][0]["content"]


def test_mcp_get_prompt_fills_missing_arguments() -> None:
    service = MCPApplicationService()

    result = service.get_prompt("news.source_diagnose", {})

    assert result.success is True
    assert "<unspecified>" in result.to_dict()["messages"][0]["content"]


def test_mcp_unknown_prompt_fails_safely() -> None:
    result = MCPApplicationService().get_prompt("news.unknown")

    assert result.success is False
    assert result.error_type == "MCPPromptNotFound"


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
    assert result.data["report_id"] == "run-1:final"
    assert result.data["run_id"] == "run-1"
    assert result.data["report_json"] == {"title": "Daily Intelligence"}
    assert result.data["report_markdown"] == "# Daily Intelligence"


def test_mcp_reads_report_resource_from_local_json_artifact(tmp_path) -> None:
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

    result = service.read_resource("news://reports/run-1:final")

    assert result.success is True
    assert result.data["report_id"] == "run-1:final"
    assert result.data["run_id"] == "run-1"
    assert result.data["report_json"] == {"title": "Daily Intelligence"}
    assert result.data["report_markdown"] == "# Daily Intelligence"


def test_mcp_report_search_reads_real_local_report_artifacts(tmp_path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    (run_dir / "report.json").write_text(
        json.dumps({"title": "AI Policy Report"}),
        encoding="utf-8",
    )
    (run_dir / "report.md").write_text("# AI Policy Report", encoding="utf-8")
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

    result = service.call_tool("news.report.search", {"query": "policy", "limit": 5})

    assert result.success is True
    assert result.data["query"] == "policy"
    assert result.data["report_count"] == 1
    assert result.data["reports"][0]["report_id"] == "run-1:final"
    assert result.data["reports"][0]["run_id"] == "run-1"


def test_mcp_report_search_requires_query() -> None:
    result = MCPApplicationService().call_tool("news.report.search", {})

    assert result.success is False
    assert result.error_type == "ValueError"
    assert "query is required" in result.error_message


def test_mcp_unknown_resource_fails_safely() -> None:
    result = MCPApplicationService().read_resource("news://missing")

    assert result.success is False
    assert result.error_type == "MCPResourceNotFound"


def test_mcp_run_show_reads_real_local_manifest(tmp_path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "status": "succeeded",
                "workflow_id": "daily_intelligence",
            }
        ),
        encoding="utf-8",
    )
    service = MCPApplicationService(
        run_inspection_service_factory=lambda: RunInspectionService(artifact_root=tmp_path)
    )

    result = service.call_tool("news.run.show", {"run_id": "run-1"})

    assert result.success is True
    assert result.data["run_id"] == "run-1"
    assert result.data["manifest"]["workflow_id"] == "daily_intelligence"


def test_mcp_reads_run_manifest_resource_from_local_manifest(tmp_path) -> None:
    run_dir = tmp_path / "run-2"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run-2",
                "status": "failed",
                "workflow_id": "daily_intelligence",
            }
        ),
        encoding="utf-8",
    )
    service = MCPApplicationService(
        run_inspection_service_factory=lambda: RunInspectionService(artifact_root=tmp_path)
    )

    result = service.read_resource("news://runs/run-2/manifest")

    assert result.success is True
    assert result.data["run_id"] == "run-2"
    assert result.data["manifest"]["status"] == "failed"


def test_mcp_run_events_reads_real_local_events(tmp_path) -> None:
    _write_run_with_events(
        tmp_path,
        "run-3",
        [
            {"event_type": "workflow_started", "payload": {"profile": "live"}},
            {"event_type": "workflow_succeeded", "payload": {"status": "ok"}},
        ],
    )
    service = MCPApplicationService(
        run_inspection_service_factory=lambda: RunInspectionService(artifact_root=tmp_path)
    )

    result = service.call_tool("news.run.events", {"run_id": "run-3", "limit": 1})

    assert result.success is True
    assert result.data["run_id"] == "run-3"
    assert result.data["event_count"] == 1
    assert result.data["events"][0]["event_type"] == "workflow_started"


def test_mcp_reads_run_events_resource_from_local_events(tmp_path) -> None:
    _write_run_with_events(
        tmp_path,
        "run-4",
        [
            {
                "event_type": "tool_called",
                "payload": {"token": "hidden-value", "safe": "visible"},
            }
        ],
    )
    service = MCPApplicationService(
        run_inspection_service_factory=lambda: RunInspectionService(artifact_root=tmp_path)
    )

    result = service.read_resource("news://runs/run-4/events")

    assert result.success is True
    assert result.data["run_id"] == "run-4"
    assert result.data["event_count"] == 1
    assert result.data["events"][0]["payload"]["token"] == "[redacted]"
    assert result.data["events"][0]["payload"]["safe"] == "visible"


def test_mcp_reads_run_artifact_resource_from_local_artifact(tmp_path) -> None:
    run_dir = tmp_path / "run-6"
    run_dir.mkdir()
    (run_dir / "output.json").write_text(json.dumps({"status": "ok"}), encoding="utf-8")
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run-6",
                "status": "succeeded",
                "artifacts": {"output": "output.json"},
            }
        ),
        encoding="utf-8",
    )
    service = MCPApplicationService(
        artifact_service_factory=lambda: ArtifactInspectionService(artifact_root=tmp_path)
    )

    result = service.read_resource("news://runs/run-6/artifacts/output")

    assert result.success is True
    assert result.data["run_id"] == "run-6"
    assert result.data["artifact_key"] == "output"
    assert result.data["content_type"] == "application/json"
    assert result.data["content"] == {"status": "ok"}


def test_mcp_run_artifact_resource_allows_events_artifact_key(tmp_path) -> None:
    run_dir = tmp_path / "run-7"
    run_dir.mkdir()
    (run_dir / "events.jsonl").write_text(
        json.dumps({"event_type": "workflow_started"}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run-7",
                "status": "succeeded",
                "artifacts": {"events": "events.jsonl"},
            }
        ),
        encoding="utf-8",
    )
    service = MCPApplicationService(
        artifact_service_factory=lambda: ArtifactInspectionService(artifact_root=tmp_path)
    )

    result = service.read_resource("news://runs/run-7/artifacts/events")

    assert result.success is True
    assert result.data["run_id"] == "run-7"
    assert result.data["artifact_key"] == "events"
    assert result.data["content_type"] == "application/x-ndjson"
    assert "workflow_started" in result.data["content"]


def test_mcp_run_artifact_resource_missing_key_fails_safely(tmp_path) -> None:
    run_dir = tmp_path / "run-8"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        json.dumps({"run_id": "run-8", "status": "succeeded", "artifacts": {}}),
        encoding="utf-8",
    )
    service = MCPApplicationService(
        artifact_service_factory=lambda: ArtifactInspectionService(artifact_root=tmp_path)
    )

    result = service.read_resource("news://runs/run-8/artifacts/missing")

    assert result.success is False
    assert result.error_type == "FileNotFoundError"
    assert "artifact not found" in result.error_message


def test_mcp_run_show_rejects_invalid_run_id() -> None:
    result = MCPApplicationService().call_tool("news.run.show", {"run_id": "../secret"})

    assert result.success is False
    assert result.error_type == "ValueError"
    assert "invalid run id" in result.error_message


def test_mcp_run_events_rejects_invalid_limit(tmp_path) -> None:
    _write_run_with_events(tmp_path, "run-5", [{"event_type": "workflow_started", "payload": {}}])
    service = MCPApplicationService(
        run_inspection_service_factory=lambda: RunInspectionService(artifact_root=tmp_path)
    )

    result = service.call_tool("news.run.events", {"run_id": "run-5", "limit": 0})

    assert result.success is False
    assert result.error_type == "ValueError"
    assert "limit must be greater than zero" in result.error_message


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


def _write_run_with_events(root, run_id, events) -> None:
    run_dir = root / run_id
    run_dir.mkdir()
    manifest = {
        "run_id": run_id,
        "status": "succeeded",
        "artifacts": {"events": "events.jsonl"},
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "events.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )
