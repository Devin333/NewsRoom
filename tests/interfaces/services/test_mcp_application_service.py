import json
from datetime import UTC, datetime

from interfaces.services.approval_service import ApprovalApplicationService
from interfaces.services.artifact_service import ArtifactInspectionService
from interfaces.services.mcp_service import MCPApplicationService
from interfaces.services.report_service import ReportApplicationService
from interfaces.services.run_inspection_service import RunInspectionService
from interfaces.services.storage_service import StorageApplicationService
from storage.artifacts import ArtifactWriteRequest, FilesystemArtifactStore, LocalJsonArtifactIndexStore
from storage.lineage import LineageRef, LocalJsonLineageStore


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
        storage_service_factory=_raising_factory,
    )

    catalog = service.catalog().to_dict()
    tool_names = [tool["name"] for tool in catalog["tools"]]
    resource_uris = [resource["uri"] for resource in catalog["resources"]]

    assert "news.daily.enqueue" in tool_names
    assert "news.report.search" in tool_names
    assert "news.run.show" in tool_names
    assert "news.run.events" in tool_names
    assert "news.run.replay" in tool_names
    assert "news.run.lineage" in tool_names
    assert "news.run.lineage.upstream" in tool_names
    assert "news.run.lineage.downstream" in tool_names
    assert "news.storage.metrics" in tool_names
    assert "news.storage.retention.plan" in tool_names
    assert "news.source.arxiv.fetch" in tool_names
    assert "news.source.github.releases" in tool_names
    assert "news.worker.status" in tool_names
    assert "news.queue.status" in tool_names
    assert "news.approval.submit" in tool_names
    assert "news://reports/latest" in resource_uris
    assert "news://reports/{report_id}" in resource_uris
    assert "news://runs/{run_id}/manifest" in resource_uris
    assert "news://runs/{run_id}/events" in resource_uris
    assert "news://runs/{run_id}/replay" in resource_uris
    assert "news://runs/{run_id}/lineage" in resource_uris
    assert "news://runs/{run_id}/lineage/upstream/{target_type}/{target_id}" in resource_uris
    assert "news://runs/{run_id}/lineage/downstream/{source_type}/{source_id}" in resource_uris
    assert "news://runs/{run_id}/artifacts/{artifact_key}" in resource_uris
    assert "news://storage/metrics" in resource_uris
    assert "news://storage/retention/plan" in resource_uris
    assert "news://workers" in resource_uris
    assert "news://workers/{worker_id}" in resource_uris
    assert "news://queues" in resource_uris
    prompt_names = [prompt["name"] for prompt in catalog["prompts"]]
    assert "news.evidence_audit" in prompt_names
    assert "news.quality_gate_explain" in prompt_names
    assert "news.trend_analysis_prompt" in prompt_names


def test_mcp_source_health_tool_calls_source_service() -> None:
    service = MCPApplicationService(source_service_factory=lambda: _FakeSourceService())

    result = service.call_tool("news.source.health", {"include_disabled": True})

    assert result.success is True
    assert result.to_dict()["data"]["health"][0]["source_id"] == "source-1"


def test_mcp_source_arxiv_fetch_tool_calls_source_service() -> None:
    service = MCPApplicationService(source_service_factory=lambda: _FakeSourceService())

    result = service.call_tool("news.source.arxiv.fetch", {"query": "cat:cs.AI", "limit": 1})

    assert result.success is True
    assert result.data["source_type"] == "arxiv"
    assert result.data["item_count"] == 1
    assert result.data["items"][0]["title"] == "Agent Runtime Evaluation"


def test_mcp_source_github_releases_tool_calls_source_service() -> None:
    service = MCPApplicationService(source_service_factory=lambda: _FakeSourceService())

    result = service.call_tool(
        "news.source.github.releases",
        {"repository": "owner/repo", "limit": 1},
    )

    assert result.success is True
    assert result.data["source_type"] == "github"
    assert result.data["item_count"] == 1
    assert result.data["items"][0]["title"] == "Version 1.0.0"


def test_mcp_source_arxiv_fetch_requires_query() -> None:
    service = MCPApplicationService(source_service_factory=lambda: _FakeSourceService())

    result = service.call_tool("news.source.arxiv.fetch", {})

    assert result.success is False
    assert result.error_type == "ValueError"
    assert "query is required" in result.error_message


def test_mcp_worker_status_tool_calls_worker_service() -> None:
    fake_worker = _FakeWorkerService()
    service = MCPApplicationService(worker_service_factory=lambda: fake_worker)

    result = service.call_tool(
        "news.worker.status",
        {"worker_id": "worker-1", "stale_after_seconds": 30},
    )

    assert result.success is True
    assert result.data["worker_count"] == 1
    assert fake_worker.calls == [{"worker_id": "worker-1", "stale_after_seconds": 30}]


def test_mcp_worker_status_resource_calls_worker_service() -> None:
    fake_worker = _FakeWorkerService()
    service = MCPApplicationService(worker_service_factory=lambda: fake_worker)

    result = service.read_resource("news://workers/worker-1?stale_after_seconds=45")

    assert result.success is True
    assert result.data["worker_id"] == "worker-1"
    assert fake_worker.calls == [{"worker_id": "worker-1", "stale_after_seconds": 45}]


def test_mcp_queue_status_tool_calls_worker_service() -> None:
    fake_worker = _FakeWorkerService()
    service = MCPApplicationService(worker_service_factory=lambda: fake_worker)

    result = service.call_tool("news.queue.status", {"queue_names": ["news:queue:daily"]})

    assert result.success is True
    assert result.data["queue_count"] == 1
    assert fake_worker.queue_calls == [["news:queue:daily"]]


def test_mcp_queue_status_resource_calls_worker_service() -> None:
    fake_worker = _FakeWorkerService()
    service = MCPApplicationService(worker_service_factory=lambda: fake_worker)

    result = service.read_resource(
        "news://queues?queue_name=news:queue:daily&queue_name=news:queue:memory"
    )

    assert result.success is True
    assert result.data["queue_count"] == 2
    assert fake_worker.queue_calls == [["news:queue:daily", "news:queue:memory"]]


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


def test_mcp_run_replay_reads_real_local_replay_bundle(tmp_path) -> None:
    _write_run_with_replay_artifacts(tmp_path, "run-replay")
    service = MCPApplicationService(
        run_inspection_service_factory=lambda: RunInspectionService(artifact_root=tmp_path)
    )

    result = service.call_tool("news.run.replay", {"run_id": "run-replay"})

    artifacts = {artifact["artifact_key"]: artifact for artifact in result.data["artifacts"]}
    assert result.success is True
    assert result.data["run_id"] == "run-replay"
    assert result.data["event_count"] == 1
    assert result.data["events"][0]["payload"]["token"] == "[redacted]"
    assert artifacts["report_json"]["content"]["api_key"] == "[redacted]"


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


def test_mcp_reads_run_replay_resource_from_local_artifacts(tmp_path) -> None:
    _write_run_with_replay_artifacts(tmp_path, "run-replay-resource")
    service = MCPApplicationService(
        run_inspection_service_factory=lambda: RunInspectionService(artifact_root=tmp_path)
    )

    result = service.read_resource("news://runs/run-replay-resource/replay")

    artifacts = {artifact["artifact_key"]: artifact for artifact in result.data["artifacts"]}
    assert result.success is True
    assert result.data["run_id"] == "run-replay-resource"
    assert result.data["artifact_count"] == 3
    assert artifacts["report_markdown"]["content"] == "# Replay\n"


def test_mcp_run_lineage_tools_read_real_local_lineage(tmp_path) -> None:
    _write_lineage_refs(tmp_path)
    service = MCPApplicationService(
        storage_service_factory=lambda: StorageApplicationService(artifact_root=tmp_path)
    )

    listed = service.call_tool("news.run.lineage", {"run_id": "run-lineage"})
    upstream = service.call_tool(
        "news.run.lineage.upstream",
        {"run_id": "run-lineage", "target_type": "evidence", "target_id": "ev-1"},
    )
    downstream = service.call_tool(
        "news.run.lineage.downstream",
        {"run_id": "run-lineage", "source_type": "source_item", "source_id": "raw-1"},
    )

    assert listed.success is True
    assert listed.data["lineage_count"] == 2
    assert upstream.success is True
    assert upstream.data["lineage_count"] == 2
    assert downstream.success is True
    assert downstream.data["lineage_count"] == 1
    assert downstream.data["lineage_refs"][0]["source_id"] == "raw-1"


def test_mcp_run_lineage_resources_read_real_local_lineage(tmp_path) -> None:
    _write_lineage_refs(tmp_path)
    service = MCPApplicationService(
        storage_service_factory=lambda: StorageApplicationService(artifact_root=tmp_path)
    )

    listed = service.read_resource("news://runs/run-lineage/lineage")
    upstream = service.read_resource("news://runs/run-lineage/lineage/upstream/evidence/ev-1")
    downstream = service.read_resource(
        "news://runs/run-lineage/lineage/downstream/source_item/raw-1"
    )

    assert listed.success is True
    assert listed.data["lineage_count"] == 2
    assert upstream.success is True
    assert upstream.data["lineage_refs"][0]["target_id"] == "ev-1"
    assert downstream.success is True
    assert downstream.data["lineage_count"] == 1


def test_mcp_storage_metrics_tool_reads_real_local_storage(tmp_path) -> None:
    _write_metric_artifacts(tmp_path)
    service = MCPApplicationService(
        storage_service_factory=lambda: StorageApplicationService(artifact_root=tmp_path)
    )

    result = service.call_tool("news.storage.metrics")

    assert result.success is True
    assert result.data["runs_count"] == 1
    assert result.data["artifacts_count"] == 1
    assert result.data["artifact_bytes_total"] > 0


def test_mcp_reads_storage_metrics_resource_from_real_local_storage(tmp_path) -> None:
    _write_metric_artifacts(tmp_path)
    service = MCPApplicationService(
        storage_service_factory=lambda: StorageApplicationService(artifact_root=tmp_path)
    )

    result = service.read_resource("news://storage/metrics")

    assert result.success is True
    assert result.data["runs_count"] == 1
    assert result.data["reports_count"] == 1
    assert result.data["metadata"]["source"] == "local_json"


def test_mcp_storage_retention_plan_tool_reads_real_local_storage(tmp_path) -> None:
    old_ref = _write_retention_artifacts(tmp_path)
    service = MCPApplicationService(
        storage_service_factory=lambda: StorageApplicationService(artifact_root=tmp_path)
    )

    result = service.call_tool(
        "news.storage.retention.plan",
        {
            "run_id": "retention-run",
            "raw_source_retention_days": 1,
            "now": "2026-05-11T00:00:00Z",
        },
    )

    assert result.success is True
    assert result.data["run_id"] == "retention-run"
    assert result.data["artifact_count"] == 2
    assert result.data["delete_count"] == 1
    assert result.data["plan"]["decisions"][0]["artifact_ref"]["artifact_id"] == "raw-old"
    assert (tmp_path / old_ref.run_id / old_ref.path).exists()


def test_mcp_reads_storage_retention_plan_resource_from_real_local_storage(tmp_path) -> None:
    _write_retention_artifacts(tmp_path)
    service = MCPApplicationService(
        storage_service_factory=lambda: StorageApplicationService(artifact_root=tmp_path)
    )

    result = service.read_resource(
        "news://storage/retention/plan?run_id=retention-run&raw_source_retention_days=1"
        "&now=2026-05-11T00%3A00%3A00Z"
    )

    assert result.success is True
    assert result.data["run_id"] == "retention-run"
    assert result.data["delete_count"] == 1
    assert result.data["keep_count"] == 1


def test_mcp_storage_retention_plan_rejects_invalid_policy() -> None:
    result = MCPApplicationService().call_tool(
        "news.storage.retention.plan",
        {"raw_source_retention_days": -1},
    )

    assert result.success is False
    assert result.error_type == "ValueError"
    assert "raw_source_retention_days" in result.error_message


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

    def fetch_arxiv(self, *, query, limit):
        return _FakeResult(
            {
                "source_id": "arxiv",
                "source_type": "arxiv",
                "query": query,
                "item_count": 1,
                "error_count": 0,
                "items": [
                    {
                        "source_item_id": "raw-arxiv",
                        "source_id": "arxiv",
                        "source_name": "arXiv",
                        "source_type": "arxiv",
                        "title": "Agent Runtime Evaluation",
                        "url": "https://arxiv.org/abs/2605.00001",
                        "fetched_at": "2026-05-11T00:00:00Z",
                        "published_at": "2026-05-10T00:00:00Z",
                        "summary": "Paper summary",
                        "raw_content": None,
                        "authors": ["Alice Example"],
                        "tags": ["cs.AI"],
                        "language": "en",
                        "metadata": {"arxiv_id": "2605.00001v1"},
                    }
                ],
                "errors": [],
            }
        )

    def fetch_github_releases(self, *, repository, limit):
        return _FakeResult(
            {
                "source_id": "github",
                "source_type": "github",
                "query": repository,
                "item_count": 1,
                "error_count": 0,
                "items": [
                    {
                        "source_item_id": "raw-github",
                        "source_id": "github",
                        "source_name": "GitHub",
                        "source_type": "github",
                        "title": "Version 1.0.0",
                        "url": "https://github.com/owner/repo/releases/tag/v1.0.0",
                        "fetched_at": "2026-05-11T00:00:00Z",
                        "published_at": "2026-05-10T00:00:00Z",
                        "summary": "Release notes",
                        "raw_content": None,
                        "authors": ["maintainer"],
                        "tags": ["v1.0.0"],
                        "language": "en",
                        "metadata": {"repository": "owner/repo"},
                    }
                ],
                "errors": [],
            }
        )


class _FakeMemoryService:
    def search(self, **kwargs):
        return _FakeResult({"result_count": 0, "results": []})


class _FakeWorkerService:
    def __init__(self) -> None:
        self.calls = []
        self.queue_calls = []

    def list_worker_status(self, *, worker_id=None, stale_after_seconds=60):
        self.calls.append(
            {
                "worker_id": worker_id,
                "stale_after_seconds": stale_after_seconds,
            }
        )
        return _FakeResult(
            {
                "worker_id": worker_id,
                "worker_count": 1,
                "unhealthy_count": 0,
                "stale_after_seconds": stale_after_seconds,
                "workers": [
                    {
                        "worker_id": "worker-1",
                        "status": "running",
                        "stale": False,
                    }
                ],
            }
        )

    def queue_status(self, *, queue_names=None):
        self.queue_calls.append(queue_names)
        actual_queue_names = queue_names or ["news:queue:daily"]
        return _FakeResult(
            {
                "queue_count": len(actual_queue_names),
                "total_stream_length": len(actual_queue_names),
                "total_pending_count": 0,
                "queues": [
                    {
                        "queue_name": queue_name,
                        "stream_length": 1,
                        "pending_count": 0,
                    }
                    for queue_name in actual_queue_names
                ],
            }
        )


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


def _write_run_with_replay_artifacts(root, run_id) -> None:
    run_dir = root / run_id
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "status": "succeeded",
                "artifacts": {
                    "events": "events.jsonl",
                    "report_json": "report.json",
                    "report_markdown": "report.md",
                },
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "events.jsonl").write_text(
        json.dumps({"event_type": "workflow_started", "payload": {"token": "hidden"}}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "report.json").write_text(
        json.dumps({"title": "Replay", "api_key": "hidden"}),
        encoding="utf-8",
    )
    (run_dir / "report.md").write_text("# Replay\n", encoding="utf-8")


def _write_lineage_refs(root) -> None:
    store = LocalJsonLineageStore(root / "_records" / "lineage")
    store.record_many(
        [
            LineageRef(
                run_id="run-lineage",
                source_type="source_item",
                source_id="raw-1",
                target_type="evidence",
                target_id="ev-1",
                relation_type="source_to_evidence",
            ),
            LineageRef(
                run_id="run-lineage",
                source_type="ranked_source_item",
                source_id="rank-1",
                target_type="evidence",
                target_id="ev-1",
                relation_type="ranked_to_evidence",
            ),
        ]
    )


def _write_metric_artifacts(root) -> None:
    artifact_store = FilesystemArtifactStore(root)
    artifact_index = LocalJsonArtifactIndexStore(root / "_records" / "artifact_index")
    ref = artifact_store.write(
        ArtifactWriteRequest(
            run_id="metrics-run",
            artifact_id="report-1",
            artifact_type="report_json",
            content=b'{"title":"Report"}',
            content_type="application/json",
        )
    )
    artifact_index.index_artifact(ref)
    (root / "metrics-run" / "manifest.json").write_text(
        json.dumps({"run_id": "metrics-run", "artifacts": {"report_json": ref.path}}),
        encoding="utf-8",
    )


def _write_retention_artifacts(root):
    artifact_store = FilesystemArtifactStore(root)
    artifact_index = LocalJsonArtifactIndexStore(root / "_records" / "artifact_index")
    old_created_at = datetime(2020, 1, 1, tzinfo=UTC)
    old_ref = artifact_store.write(
        ArtifactWriteRequest(
            run_id="retention-run",
            artifact_id="raw-old",
            artifact_type="source_item",
            content="old source",
            content_type="text/plain",
            created_at=old_created_at,
        )
    )
    report_ref = artifact_store.write(
        ArtifactWriteRequest(
            run_id="retention-run",
            artifact_id="report-keep",
            artifact_type="report_json",
            content=b'{"title":"Keep"}',
            content_type="application/json",
            created_at=old_created_at,
        )
    )
    artifact_index.index_artifact(old_ref)
    artifact_index.index_artifact(report_ref)
    return old_ref
