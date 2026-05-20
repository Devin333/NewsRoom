import json
from datetime import UTC, datetime

from framework.run_result import RunResult
from core.framework.specs import WorkflowStatus
from interfaces.services.approval_service import ApprovalApplicationService
from interfaces.services.artifact_service import ArtifactInspectionService
from interfaces.services.entity_service import EntityTrackingApplicationService
from interfaces.services.memory_service import MemoryApplicationService
from interfaces.services.mcp_service import MCPApplicationService
from interfaces.services.report_service import ReportApplicationService
from interfaces.services.run_inspection_service import RunInspectionService
from interfaces.services.run_service import RunApplicationService
from interfaces.services.storage_service import StorageApplicationService
from interfaces.services.subscription_service import SubscriptionApplicationService
from workflows.daily_intelligence.profiles import LEGACY_DAILY_WORKFLOW_ID
from storage.artifacts import ArtifactWriteRequest, FilesystemArtifactStore, LocalJsonArtifactIndexStore
from storage.lineage import LineageRef, LocalJsonLineageStore
from storage.vector import InMemoryVectorStore


def test_mcp_catalog_lists_tools_without_calling_factories() -> None:
    service = MCPApplicationService(
        worker_service_factory=_raising_factory,
        run_service_factory=_raising_factory,
        report_service_factory=_raising_factory,
        source_service_factory=_raising_factory,
        entity_service_factory=_raising_factory,
        subscription_service_factory=_raising_factory,
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
    assert "news.daily.run" in tool_names
    assert "news.weekly.run" in tool_names
    assert "news.report.list" in tool_names
    assert "news.report.get" in tool_names
    assert "news.report.search" in tool_names
    assert "news.run.show" in tool_names
    assert "news.run.events" in tool_names
    assert "news.run.replay" in tool_names
    assert "news.run.diagnostics" in tool_names
    assert "news.run.health" in tool_names
    assert "news.run.catalog_health" in tool_names
    assert "news.run.compare" in tool_names
    assert "news.run.lineage" in tool_names
    assert "news.run.lineage.upstream" in tool_names
    assert "news.run.lineage.downstream" in tool_names
    assert "news.storage.metrics" in tool_names
    assert "news.storage.retention.plan" in tool_names
    assert "news.source.arxiv.fetch" in tool_names
    assert "news.source.github.releases" in tool_names
    assert "news.entity.list" in tool_names
    assert "news.entity.create" in tool_names
    assert "news.entity.match_reports" in tool_names
    assert "news.subscription.list" in tool_names
    assert "news.subscription.create" in tool_names
    assert "news.memory.reindex" in tool_names
    assert "news.memory.bootstrap" in tool_names
    assert "news.worker.status" in tool_names
    assert "news.queue.status" in tool_names
    assert "news.approval.submit" in tool_names
    assert "news.approval.resume_context" in tool_names
    assert "news.approval.resume_workflow" in tool_names
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


def test_mcp_catalog_daily_profile_schemas_include_agentic_profiles() -> None:
    catalog = MCPApplicationService().catalog().to_dict()
    tools = {tool["name"]: tool for tool in catalog["tools"]}

    for tool_name in [
        "news.daily.enqueue",
        "news.daily.run",
        "news.topic.run",
        "news.subscription.create",
    ]:
        profile_enum = tools[tool_name]["input_schema"]["properties"]["profile"]["enum"]
        assert "agentic-offline" in profile_enum
        assert "agentic-live" in profile_enum


def test_mcp_capability_manifest_describes_tools_resources_and_prompts() -> None:
    service = MCPApplicationService(
        worker_service_factory=_raising_factory,
        run_service_factory=_raising_factory,
        report_service_factory=_raising_factory,
        source_service_factory=_raising_factory,
        entity_service_factory=_raising_factory,
        subscription_service_factory=_raising_factory,
        memory_service_factory=_raising_factory,
        diagnostic_service_factory=_raising_factory,
        approval_service_factory=_raising_factory,
        run_inspection_service_factory=_raising_factory,
        artifact_service_factory=_raising_factory,
        storage_service_factory=_raising_factory,
    )

    manifest = service.capability_manifest().to_dict()
    capabilities = {capability["name"]: capability for capability in manifest["capabilities"]}

    assert manifest["version"] == "1.0"
    assert manifest["schema_version"] == "newsroom.mcp_capability_manifest.v1"
    assert manifest["server_name"] == "NewsRoom"
    assert manifest["boundary"] == "inbound_mcp_server"
    assert manifest["capability_count"] == len(manifest["capabilities"])
    assert all(capability["boundary"] == "inbound_mcp_server" for capability in capabilities.values())
    assert all(capability["category"] for capability in capabilities.values())
    assert all(capability["permission"] for capability in capabilities.values())
    assert capabilities["news.report.latest"]["kind"] == "tool"
    assert capabilities["news.report.latest"]["read_only"] is True
    assert capabilities["news.report.latest"]["permission"] == "read:reports"
    assert capabilities["news.report.latest"]["category"] == "reports"
    assert capabilities["news.daily.run"]["read_only"] is False
    assert capabilities["news.daily.run"]["permission"] == "write:runs"
    assert capabilities["news.daily.run"]["category"] == "runs"
    assert capabilities["news.report.publish"]["requires_approval"] is True
    assert capabilities["news.report.publish"]["risk_level"] == "high"
    assert capabilities["news.approval.resume_context"]["permission"] == "manage:approvals"
    assert capabilities["news.approval.resume_context"]["read_only"] is True
    assert capabilities["news.approval.resume_context"]["category"] == "approvals"
    assert capabilities["news.approval.resume_workflow"]["permission"] == "manage:approvals"
    assert capabilities["news.approval.resume_workflow"]["read_only"] is False
    assert capabilities["news.approval.resume_workflow"]["category"] == "approvals"
    assert capabilities["news://runs/{run_id}/manifest"]["kind"] == "resource"
    assert capabilities["news://runs/{run_id}/manifest"]["read_only"] is True
    assert capabilities["news://runs/{run_id}/manifest"]["permission"] == "read:reports"
    assert capabilities["news://storage/metrics"]["permission"] == "admin:storage"
    assert capabilities["news://reports/latest"]["permission"] == "read:reports"
    assert capabilities["news://runs/{run_id}/manifest"]["metadata"]["redacted"] is True
    assert capabilities["news.evidence_audit"]["kind"] == "prompt"
    assert capabilities["news.evidence_audit"]["permission"] == "mcp:read"


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


def test_mcp_source_github_releases_requires_repository() -> None:
    service = MCPApplicationService(source_service_factory=lambda: _FakeSourceService())

    result = service.call_tool("news.source.github.releases", {})

    assert result.success is False
    assert result.error_type == "ValueError"
    assert "repository is required" in result.error_message


def test_mcp_run_tools_use_configured_run_service_factory() -> None:
    run_service = _FakeRunService()
    worker_service = _FakeWorkerService()
    service = MCPApplicationService(
        run_service_factory=lambda: run_service,
        worker_service_factory=lambda: worker_service,
    )

    daily = service.call_tool(
        "news.daily.run",
        {
            "profile": "live-offline",
            "topic": "AI policy",
            "source_limit": 2,
            "run_id": "daily-run",
        },
    )
    topic = service.call_tool(
        "news.topic.run",
        {"topic": "Runtime", "source_limit": 1, "run_id": "topic-run"},
    )
    weekly = service.call_tool(
        "news.weekly.run",
        {"topic": "AI policy", "source_limit": 5, "run_id": "weekly-run"},
    )
    queued = service.call_tool(
        "news.daily.enqueue",
        {"topic": "AI policy", "source_limit": 3, "run_id": "queued-run"},
    )

    assert daily.success is True
    assert topic.success is True
    assert weekly.success is True
    assert queued.success is True
    assert [call["kind"] for call in run_service.calls] == ["daily", "daily", "weekly"]
    assert run_service.calls[0]["topic"] == "AI policy"
    assert run_service.calls[1]["topic"] == "Runtime"
    assert run_service.calls[2]["run_id"] == "weekly-run"
    assert worker_service.enqueue_calls[0]["run_id"] == "queued-run"
    assert queued.data["task"]["status"] == "queued"
    assert queued.data["task"]["queue_name"] == "news:queue:daily"
    assert daily.data["run_id"] == "daily-run"
    assert weekly.data["workflow_id"] == "weekly-intelligence"
    assert queued.data["task"]["task_id"] == "task-1"


def test_mcp_daily_and_weekly_run_use_real_runners(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("NEWS_DATABASE_DSN", raising=False)
    service = MCPApplicationService(
        run_service_factory=lambda: RunApplicationService(artifact_root=tmp_path)
    )

    daily = service.call_tool(
        "news.daily.run",
        {
            "profile": "live-offline",
            "topic": "AI policy",
            "source_limit": 2,
            "run_id": "mcp-daily-run",
        },
    )
    weekly = service.call_tool(
        "news.weekly.run",
        {
            "topic": "AI policy",
            "source_limit": 5,
            "period_start": "2026-05-01T00:00:00Z",
            "period_end": "2026-05-20T00:00:00Z",
            "run_id": "mcp-weekly-run",
        },
    )

    assert daily.success is True
    assert daily.data["run_id"] == "mcp-daily-run"
    assert daily.data["workflow_id"] == "daily-intelligence-agentic"
    assert daily.data["status"] == "succeeded"
    assert weekly.success is True
    assert weekly.data["run_id"] == "mcp-weekly-run"
    assert weekly.data["workflow_id"] == "weekly-intelligence"
    assert weekly.data["status"] == "succeeded"
    assert weekly.data["output"]["weekly_metrics"]["source_report_count"] == 1
    assert (tmp_path / "mcp-daily-run" / "manifest.json").exists()
    assert (tmp_path / "mcp-weekly-run" / "manifest.json").exists()


def test_mcp_daily_run_returns_runner_validation_error(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("NEWS_DATABASE_DSN", raising=False)
    service = MCPApplicationService(
        run_service_factory=lambda: RunApplicationService(artifact_root=tmp_path)
    )

    result = service.call_tool("news.daily.run", {"profile": "unsupported"})

    assert result.success is False
    assert result.error_type == "ValueError"
    assert "unsupported daily intelligence profile" in result.error_message


def test_mcp_entity_match_reports_accepts_daily_workflow_family(tmp_path) -> None:
    store_path = tmp_path / "entities.json"
    artifact_root = tmp_path / "runs"
    _write_report_run(
        artifact_root,
        "run-entity-family",
        "Daily Intelligence: OpenAI",
        "OpenAI and ChatGPT were cited in this report.",
    )
    service = MCPApplicationService(
        entity_service_factory=lambda: EntityTrackingApplicationService(store_path=store_path)
    )
    created = service.call_tool(
        "news.entity.create",
        {"name": "OpenAI", "kind": "company", "aliases": ["ChatGPT"]},
    )

    result = service.call_tool(
        "news.entity.match_reports",
        {
            "entity_id": created.data["entity_id"],
            "artifact_root": str(artifact_root),
            "workflow_family": "daily",
        },
    )

    assert result.success is True
    assert result.data["workflow_family"] == "daily"
    assert result.data["match_count"] == 1


    store_path = tmp_path / "entities.json"
    service = MCPApplicationService(
        entity_service_factory=lambda: EntityTrackingApplicationService(store_path=store_path)
    )

    created = service.call_tool(
        "news.entity.create",
        {
            "name": "OpenAI",
            "kind": "company",
            "aliases": ["ChatGPT"],
            "enabled": False,
            "metadata": {"sector": "AI"},
        },
    )
    entity_id = created.data["entity_id"]
    listed = service.call_tool("news.entity.list", {"kind": "company"})
    enabled = service.call_tool("news.entity.enable", {"entity_id": entity_id})
    disabled = service.call_tool("news.entity.disable", {"entity_id": entity_id})
    deleted = service.call_tool("news.entity.delete", {"entity_id": entity_id})

    assert store_path.exists()
    assert created.success is True
    assert created.data["aliases"] == ["ChatGPT"]
    assert listed.data["entity_count"] == 1
    assert enabled.data["enabled"] is True
    assert disabled.data["enabled"] is False
    assert deleted.data == {"entity_id": entity_id, "deleted": True}


def test_mcp_entity_match_reports_reads_real_local_report_artifacts(tmp_path) -> None:
    store_path = tmp_path / "entities.json"
    artifact_root = tmp_path / "runs"
    _write_report_run(
        artifact_root,
        "run-entity",
        "Daily Intelligence: OpenAI",
        "OpenAI and ChatGPT were cited in this report.",
    )
    service = MCPApplicationService(
        entity_service_factory=lambda: EntityTrackingApplicationService(store_path=store_path)
    )
    created = service.call_tool(
        "news.entity.create",
        {"name": "OpenAI", "kind": "company", "aliases": ["ChatGPT"]},
    )

    result = service.call_tool(
        "news.entity.match_reports",
        {
            "entity_id": created.data["entity_id"],
            "artifact_root": str(artifact_root),
            "workflow_id": LEGACY_DAILY_WORKFLOW_ID,
        },
    )

    assert result.success is True
    assert result.data["match_count"] == 1
    assert result.data["matches"][0]["report_id"] == "run-entity:final"
    assert result.data["matches"][0]["matched_aliases"] == ["OpenAI", "ChatGPT"]


def test_mcp_entity_create_requires_name() -> None:
    result = MCPApplicationService().call_tool("news.entity.create", {})

    assert result.success is False
    assert result.error_type == "ValueError"
    assert "name is required" in result.error_message


def test_mcp_subscription_tools_use_real_local_json_service(tmp_path) -> None:
    store_path = tmp_path / "subscriptions.json"
    service = MCPApplicationService(
        subscription_service_factory=lambda: SubscriptionApplicationService(store_path=store_path)
    )

    created = service.call_tool(
        "news.subscription.create",
        {
            "topic": "AI Policy",
            "cadence": "weekly",
            "profile": "live-offline",
            "source_limit": 3,
            "enabled": False,
            "metadata": {"owner": "research"},
        },
    )
    subscription_id = created.data["subscription_id"]
    listed = service.call_tool("news.subscription.list", {"cadence": "weekly"})
    enabled = service.call_tool("news.subscription.enable", {"subscription_id": subscription_id})
    disabled = service.call_tool("news.subscription.disable", {"subscription_id": subscription_id})
    deleted = service.call_tool("news.subscription.delete", {"subscription_id": subscription_id})

    assert store_path.exists()
    assert created.success is True
    assert created.data["source_limit"] == 3
    assert listed.data["subscription_count"] == 1
    assert enabled.data["enabled"] is True
    assert disabled.data["enabled"] is False
    assert deleted.data == {"subscription_id": subscription_id, "deleted": True}


def test_mcp_subscription_create_requires_topic() -> None:
    result = MCPApplicationService().call_tool("news.subscription.create", {})

    assert result.success is False
    assert result.error_type == "ValueError"
    assert "topic is required" in result.error_message


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


def test_mcp_memory_reindex_reads_real_artifacts_and_indexes(tmp_path) -> None:
    _write_memory_run_artifacts(tmp_path, "memory-run")
    store = InMemoryVectorStore()
    service = MCPApplicationService(
        memory_service_factory=lambda: MemoryApplicationService(
            vector_store=store,
            artifact_root=tmp_path,
        )
    )

    result = service.call_tool("news.memory.reindex", {"run_id": "memory-run"})
    search = service.call_tool(
        "news.memory.search",
        {
            "query": "Agent runtime memory",
            "collection": "report_sections",
            "filters": {"topic": "AI policy"},
        },
    )

    assert result.success is True
    assert result.data["run_id"] == "memory-run"
    assert result.data["topic"] == "AI policy"
    assert result.data["documents_indexed"] == 2
    assert result.data["collections"] == ["evidence_items", "report_sections"]
    assert "memory-run:report_section:0" in result.data["document_ids"]
    assert search.success is True
    assert search.data["result_count"] == 1


def test_mcp_memory_reindex_requires_run_id() -> None:
    result = MCPApplicationService().call_tool("news.memory.reindex", {})

    assert result.success is False
    assert result.error_type == "ValueError"
    assert "run_id is required" in result.error_message


def test_mcp_memory_bootstrap_uses_real_in_memory_vector_store() -> None:
    store = InMemoryVectorStore()
    service = MCPApplicationService(
        memory_service_factory=lambda: MemoryApplicationService(vector_store=store)
    )

    created = service.call_tool("news.memory.bootstrap", {"collections": ["custom_memory"]})
    existing = service.call_tool("news.memory.bootstrap", {"collections": ["custom_memory"]})

    assert created.success is True
    assert created.data["collection_count"] == 1
    assert created.data["created_collections"] == ["custom_memory"]
    assert created.data["existing_collections"] == []
    assert existing.success is True
    assert existing.data["created_collections"] == []
    assert existing.data["existing_collections"] == ["custom_memory"]


def test_mcp_approval_tools_persist_submit_approve_and_read(tmp_path) -> None:
    store_path = tmp_path / "approvals.json"
    run_service = _FakeRunService()
    service = MCPApplicationService(
        approval_service_factory=lambda: ApprovalApplicationService(store_path=store_path),
        run_service_factory=lambda: run_service,
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
    resume_context = service.call_tool(
        "news.approval.resume_context",
        {"approval_id": approval_id, "decision_key": "editor_decision"},
    )
    resume_workflow = service.call_tool(
        "news.approval.resume_workflow",
        {
            "approval_id": approval_id,
            "workflow_id": "test-no-llm",
            "profile": "test-no-llm",
            "run_id": "approval-resumed-run",
            "decision_key": "editor_decision",
            "checkpoint_store_path": str(tmp_path / "checkpoints"),
        },
    )

    assert store_path.exists()
    assert approved.success is True
    assert approved.data["approval"]["status"] == "approved"
    assert approved.data["approval"]["decision"]["decided_by"] == "operator"
    assert fetched.data["approval"]["status"] == "approved"
    assert listed.data["approval_count"] == 1
    assert listed.data["approvals"][0]["approval_id"] == approval_id
    assert resume_context.success is True
    assert resume_context.data["decision_key"] == "editor_decision"
    assert resume_context.data["buffer_updates"]["editor_decision"]["approval_id"] == approval_id
    assert resume_context.data["resume_metadata"]["approval_run_id"] == "run-1"
    assert resume_workflow.success is True
    assert resume_workflow.data["run_id"] == "approval-resumed-run"
    assert run_service.calls[0]["kind"] == "approval_resume"
    assert run_service.calls[0]["approval_id"] == approval_id
    assert run_service.calls[0]["workflow_id"] == "test-no-llm"
    assert run_service.calls[0]["decision_key"] == "editor_decision"


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


def test_mcp_report_list_reads_real_local_report_artifacts(tmp_path) -> None:
    _write_report_run(
        tmp_path,
        "run-list-1",
        "Daily Intelligence: OpenAI",
        "OpenAI appeared in the report.",
    )
    _write_report_run(
        tmp_path,
        "run-list-2",
        "Daily Intelligence: Anthropic",
        "Anthropic appeared in the report.",
    )
    service = MCPApplicationService(
        report_service_factory=lambda: ReportApplicationService(artifact_root=tmp_path)
    )

    result = service.call_tool(
        "news.report.list",
        {"workflow_id": LEGACY_DAILY_WORKFLOW_ID, "limit": 5},
    )

    assert result.success is True
    assert result.data["workflow_id"] == LEGACY_DAILY_WORKFLOW_ID
    assert result.data["report_count"] == 2
    assert {report["report_id"] for report in result.data["reports"]} == {
        "run-list-1:final",
        "run-list-2:final",
    }


def test_mcp_report_list_accepts_daily_workflow_family(tmp_path) -> None:
    _write_report_run(
        tmp_path,
        "run-list-family",
        "Daily Intelligence: OpenAI",
        "OpenAI appeared in the report.",
    )
    service = MCPApplicationService(
        report_service_factory=lambda: ReportApplicationService(artifact_root=tmp_path)
    )

    result = service.call_tool(
        "news.report.list",
        {"workflow_family": "daily", "limit": 5},
    )

    assert result.success is True
    assert result.data["workflow_family"] == "daily"
    assert result.data["report_count"] == 1


    _write_report_run(
        tmp_path,
        "run-get-1",
        "Daily Intelligence: OpenAI",
        "OpenAI appeared in the report.",
    )
    service = MCPApplicationService(
        report_service_factory=lambda: ReportApplicationService(artifact_root=tmp_path)
    )

    result = service.call_tool("news.report.get", {"report_id": "run-get-1:final"})

    assert result.success is True
    assert result.data["report_id"] == "run-get-1:final"
    assert result.data["run_id"] == "run-get-1"
    assert result.data["report_json"]["title"] == "Daily Intelligence: OpenAI"


def test_mcp_report_get_requires_report_id() -> None:
    result = MCPApplicationService().call_tool("news.report.get", {})

    assert result.success is False
    assert result.error_type == "ValueError"
    assert "report_id is required" in result.error_message


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


def test_mcp_run_diagnostics_and_health_read_real_local_run(tmp_path) -> None:
    _write_complete_inspection_run(tmp_path, "run-diagnostics")
    service = MCPApplicationService(
        run_inspection_service_factory=lambda: RunInspectionService(artifact_root=tmp_path)
    )

    diagnostics = service.call_tool("news.run.diagnostics", {"run_id": "run-diagnostics"})
    health = service.call_tool("news.run.health", {"run_id": "run-diagnostics"})

    assert diagnostics.success is True
    assert diagnostics.data["diagnostics"]["healthy"] is True
    assert health.success is True
    assert health.data["health"]["severity"] == "ok"


def test_mcp_run_catalog_health_and_compare_read_real_local_runs(tmp_path) -> None:
    _write_complete_inspection_run(tmp_path, "run-v1", workflow_version="1.0")
    _write_complete_inspection_run(tmp_path, "run-v2", workflow_version="2.0")
    service = MCPApplicationService(
        run_inspection_service_factory=lambda: RunInspectionService(artifact_root=tmp_path)
    )

    catalog_health = service.call_tool("news.run.catalog_health", {})
    comparison = service.call_tool(
        "news.run.compare",
        {"base_run_id": "run-v1", "target_run_id": "run-v2"},
    )

    assert catalog_health.success is True
    assert catalog_health.data["health"]["run_count"] == 2
    assert comparison.success is True
    assert comparison.data["comparison"]["workflow_version_changed"] is True


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


class _FakeRunService:
    def __init__(self) -> None:
        self.calls = []

    def run_daily(self, **kwargs):
        self.calls.append({"kind": "daily", **kwargs})
        return RunResult(
            run_id=kwargs.get("run_id") or "daily-run",
            workflow_id=LEGACY_DAILY_WORKFLOW_ID,
            workflow_version="1.0",
            status=WorkflowStatus.SUCCEEDED,
            output={"topic": kwargs.get("topic")},
        )

    def run_weekly(self, **kwargs):
        self.calls.append({"kind": "weekly", **kwargs})
        return RunResult(
            run_id=kwargs.get("run_id") or "weekly-run",
            workflow_id="weekly-intelligence",
            workflow_version="1.0",
            status=WorkflowStatus.SUCCEEDED,
            output={"topic": kwargs.get("topic")},
        )

    def resume_from_approval(self, approval_id, **kwargs):
        self.calls.append({"kind": "approval_resume", "approval_id": approval_id, **kwargs})
        return _FakeApprovalWorkflowResumeResult(
            approval_id=approval_id,
            run_id=kwargs.get("run_id") or "approval-resumed-run",
        )


class _FakeApprovalWorkflowResumeResult:
    def __init__(self, *, approval_id: str, run_id: str) -> None:
        self.approval_id = approval_id
        self.run_id = run_id

    def to_dict(self):
        return {
            "approval_context": {"approval_id": self.approval_id},
            "run_result": {
                "run_id": self.run_id,
                "workflow_id": "daily-intelligence-test-no-llm",
                "workflow_version": "0.1.0",
                "status": "succeeded",
                "output": {"ok": True},
                "artifact_dir": None,
                "manifest_path": None,
                "events_path": None,
                "error": None,
                "manifest": {},
            },
            "run_id": self.run_id,
            "workflow_id": "daily-intelligence-test-no-llm",
            "workflow_version": "0.1.0",
            "status": "succeeded",
            "output": {"ok": True},
            "artifact_dir": None,
            "manifest_path": None,
            "events_path": None,
            "error": None,
        }


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
        self.enqueue_calls = []

    def enqueue_daily(self, **kwargs):
        self.enqueue_calls.append(kwargs)
        return _FakeResult(
            {
                "message_id": "msg-1",
                "task": {
                    "task_id": "task-1",
                    "task_type": "daily_intelligence.run",
                    "queue_name": kwargs["queue_name"],
                    "status": "queued",
                    "payload": {
                        "topic": kwargs["topic"],
                        "source_limit": kwargs["source_limit"],
                        "run_id": kwargs["run_id"],
                    },
                },
            }
        )

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


def _write_report_run(root, run_id: str, title: str, body: str) -> None:
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "report.json").write_text(
        json.dumps(
            {
                "title": title,
                "sections": [
                    {
                        "title": "Summary",
                        "content": body,
                        "sources": ["https://example.com/report"],
                    }
                ],
                "source_urls": ["https://example.com/report"],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "report.md").write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "workflow_id": LEGACY_DAILY_WORKFLOW_ID,
                "profile": "live-offline",
                "status": "succeeded",
                "finished_at": "2026-05-11T00:00:00Z",
                "quality_score": 0.9,
                "artifacts": {
                    "report_json": "report.json",
                    "report_markdown": "report.md",
                },
            }
        ),
        encoding="utf-8",
    )


def _write_memory_run_artifacts(root, run_id: str) -> None:
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "status": "succeeded",
                "artifacts": {
                    "request": "request.json",
                    "report_json": "report.json",
                    "evidence_bundle": "evidence_bundle.json",
                },
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "request.json").write_text(json.dumps({"topic": "AI policy"}), encoding="utf-8")
    (run_dir / "report.json").write_text(
        json.dumps(
            {
                "title": "Daily Intelligence",
                "sections": [
                    {
                        "title": "Summary",
                        "content": "Agent runtime memory improved.",
                        "sources": ["https://example.com/memory"],
                    }
                ],
                "source_urls": ["https://example.com/memory"],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "evidence_bundle.json").write_text(
        json.dumps(
            {
                "bundle_id": "daily",
                "items": [
                    {
                        "evidence_id": "ev-1",
                        "source_url": "https://example.com/memory",
                        "source_id": "source-1",
                        "title": "Agent runtime memory",
                        "summary": "A runtime improved memory recall.",
                        "confidence": 0.9,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


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


def _write_complete_inspection_run(root, run_id, *, workflow_version="1.0") -> None:
    run_dir = root / run_id
    run_dir.mkdir()
    artifacts = {
        "request": "request.json",
        "workflow_spec": "workflow_spec.json",
        "workflow_version": "workflow_version.json",
        "events": "events.jsonl",
        "manifest": "manifest.json",
        "data_buffer_snapshot": "data_buffer_snapshot.json",
        "data_buffer_initial": "data_buffer.initial.json",
        "data_buffer_final": "data_buffer.final.json",
        "data_buffer_diff": "data_buffer.diff.json",
        "step_results": "step_results.json",
        "metrics": "metrics.json",
        "redaction_report": "redaction_report.json",
        "output": "output.json",
    }
    manifest = {
        "schema_version": "newsroom.workflow_run_manifest.v1",
        "run_id": run_id,
        "workflow_id": "daily",
        "workflow_version": workflow_version,
        "profile": "test",
        "status": "succeeded",
        "started_at": "2026-05-14T01:00:00Z",
        "finished_at": "2026-05-14T01:00:01Z",
        "path": ["step"],
        "steps": {"step": {"status": "succeeded", "outputs": {"report": "ok"}}},
        "artifacts": artifacts,
        "step_count": 1,
        "event_count": 2,
        "checkpoint_count": 0,
    }
    payloads = {
        "request.json": {"topic": "ai"},
        "workflow_spec.json": {"workflow_id": "daily"},
        "workflow_version.json": {"workflow_version": workflow_version},
        "data_buffer_snapshot.json": {"request": {"topic": "ai"}, "report": "ok"},
        "data_buffer.initial.json": {"request": {"topic": "ai"}},
        "data_buffer.final.json": {"request": {"topic": "ai"}, "report": "ok"},
        "data_buffer.diff.json": {"added": {"report": "ok"}, "changed": {}, "removed": {}},
        "step_results.json": {"step": {"status": "succeeded", "outputs": {"report": "ok"}}},
        "metrics.json": {"status": "succeeded", "step_count": 1},
        "redaction_report.json": {"redacted": False},
        "output.json": {"report": "ok"},
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for relative_path, payload in payloads.items():
        (run_dir / relative_path).write_text(json.dumps(payload), encoding="utf-8")
    (run_dir / "events.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"event_type": "workflow_started", "run_id": run_id, "payload": {}}),
                json.dumps({"event_type": "workflow_succeeded", "run_id": run_id, "payload": {}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )


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
