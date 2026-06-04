import json
from dataclasses import dataclass

from interfaces.services.approval_service import ApprovalApplicationService
from interfaces.services.mcp_service import MCPApplicationService
from interfaces.services.report_service import ReportApplicationService


def test_mcp_catalog_lists_research_tools_without_calling_factories() -> None:
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
        research_service_factory=_raising_factory,
    )

    catalog = service.catalog().to_dict()
    tool_names = {tool["name"] for tool in catalog["tools"]}
    resource_uris = {resource["uri"] for resource in catalog["resources"]}
    prompt_names = {prompt["name"] for prompt in catalog["prompts"]}

    assert {
        "news.research.analyze_paper",
        "news.research.paper_analysis",
        "news.research.reader",
        "news.research.ask",
        "news.research.trace",
        "news.report.list",
        "news.run.show",
        "news.source.arxiv.fetch",
        "news.source.github.releases",
        "news.worker.status",
        "news.queue.status",
        "news.approval.resume_context",
    } <= tool_names
    assert not {"news.daily.enqueue", "news.daily.run", "news.weekly.run"} & tool_names
    assert {
        "news://reports/latest",
        "news://runs/{run_id}/manifest",
        "news://runs/{run_id}/events",
        "news://runs/{run_id}/replay",
        "news://storage/metrics",
        "news://workers",
        "news://queues",
    } <= resource_uris
    assert "news.research.paper_briefing" in prompt_names
    assert "news.evidence_audit" in prompt_names


def test_mcp_capability_manifest_describes_research_permissions() -> None:
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
        research_service_factory=_raising_factory,
    )

    manifest = service.capability_manifest().to_dict()
    capabilities = {capability["name"]: capability for capability in manifest["capabilities"]}

    assert manifest["schema_version"] == "newsroom.mcp_capability_manifest.v1"
    assert capabilities["news.research.analyze_paper"]["permission"] == "write:runs"
    assert capabilities["news.research.analyze_paper"]["read_only"] is False
    assert capabilities["news.research.analyze_paper"]["category"] == "research"
    assert capabilities["news.research.reader"]["permission"] == "read:reports"
    assert capabilities["news.research.reader"]["read_only"] is True
    assert capabilities["news.report.publish"]["requires_approval"] is True
    assert capabilities["news://runs/{run_id}/manifest"]["kind"] == "resource"
    assert capabilities["news://storage/metrics"]["permission"] == "admin:storage"
    assert capabilities["news.research.paper_briefing"]["kind"] == "prompt"


def test_mcp_research_tools_use_configured_research_service_factory() -> None:
    research_service = _FakeResearchService()
    service = MCPApplicationService(research_service_factory=lambda: research_service)

    analyzed = service.call_tool(
        "news.research.analyze_paper",
        {
            "paper_id": "paper-1",
            "source_url": "https://arxiv.org/abs/2605.00001",
            "run_id": "research-run-1",
            "metadata": {"collection": "benchmarks"},
        },
    )
    analysis = service.call_tool("news.research.paper_analysis", {"paper_id": "paper-1"})
    reader = service.call_tool("news.research.reader", {"paper_id": "paper-1"})
    answer = service.call_tool(
        "news.research.ask",
        {"paper_id": "paper-1", "question": "What is the method?", "locale": "en"},
    )
    trace = service.call_tool("news.research.trace", {"run_id": "research-run-1"})

    assert analyzed.success is True
    assert analysis.success is True
    assert reader.success is True
    assert answer.success is True
    assert trace.success is True
    assert analyzed.data["runId"] == "research-run-1"
    assert analysis.data["analysis"]["summary"] == "Grounded analysis"
    assert reader.data["paper"]["paperId"] == "paper-1"
    assert answer.data["evidenceRefs"] == ["ev-1"]
    assert trace.data["trace"]["phases"] == ["PLAN", "EXECUTE", "VERIFY"]
    assert research_service.calls[0][0] == "analyze_paper"


def test_mcp_source_tools_call_source_service() -> None:
    service = MCPApplicationService(source_service_factory=lambda: _FakeSourceService())

    health = service.call_tool("news.source.health", {"include_disabled": True})
    arxiv = service.call_tool("news.source.arxiv.fetch", {"query": "cat:cs.AI", "limit": 1})
    github = service.call_tool("news.source.github.releases", {"repository": "owner/repo", "limit": 1})

    assert health.success is True
    assert health.data["health"][0]["source_id"] == "source-1"
    assert arxiv.success is True
    assert arxiv.data["items"][0]["title"] == "Agent Runtime Evaluation"
    assert github.success is True
    assert github.data["items"][0]["title"] == "Version 1.0.0"


def test_mcp_worker_and_queue_tools_call_worker_service() -> None:
    fake_worker = _FakeWorkerService()
    service = MCPApplicationService(worker_service_factory=lambda: fake_worker)

    worker = service.call_tool("news.worker.status", {"worker_id": "worker-1"})
    queue = service.call_tool("news.queue.status", {"queue_names": ["news:queue:memory"]})
    queue_resource = service.read_resource("news://queues?queue_name=news:queue:memory")

    assert worker.success is True
    assert queue.success is True
    assert queue_resource.success is True
    assert fake_worker.queue_calls == [["news:queue:memory"], ["news:queue:memory"]]


def test_mcp_approval_resume_context_stays_context_only(tmp_path) -> None:
    approval_service = ApprovalApplicationService(store_path=tmp_path / "approvals.json")
    service = MCPApplicationService(approval_service_factory=lambda: approval_service)
    submitted = service.call_tool(
        "news.approval.submit",
        {
            "requested_action": "review_report",
            "reason": "operator review required",
            "payload": {"report_id": "report-1"},
            "run_id": "run-1",
            "requested_by": "worker",
        },
    )

    approval_id = submitted.data["approval_id"]
    service.call_tool("news.approval.approve", {"approval_id": approval_id, "decided_by": "operator"})
    resume_context = service.call_tool(
        "news.approval.resume_context",
        {"approval_id": approval_id, "decision_key": "editor_decision"},
    )
    resume_workflow = service.call_tool("news.approval.resume_workflow", {"approval_id": approval_id})

    assert resume_context.success is True
    assert resume_context.data["decision_key"] == "editor_decision"
    assert resume_context.data["buffer_updates"]["editor_decision"]["approval_id"] == approval_id
    assert resume_workflow.success is False
    assert resume_workflow.error_type == "MCPToolNotFound"


def test_mcp_report_list_reads_real_local_report_artifacts(tmp_path) -> None:
    _write_report_run(tmp_path, "run-1", "Research Report", "Grounded paper analysis.")
    service = MCPApplicationService(
        report_service_factory=lambda: ReportApplicationService(artifact_root=tmp_path)
    )

    result = service.call_tool("news.report.list", {"limit": 5})

    assert result.success is True
    assert result.data["report_count"] == 1
    assert result.data["reports"][0]["title"] == "Research Report"


def test_mcp_get_research_prompt_renders_arguments() -> None:
    service = MCPApplicationService()

    result = service.get_prompt(
        "news.research.paper_briefing",
        {"paper_id": "paper-1", "question": "What is new?"},
    )

    assert result.success is True
    content = result.to_dict()["messages"][0]["content"]
    assert "paper-1" in content
    assert "What is new?" in content


def test_mcp_unknown_tool_and_resource_fail_safely() -> None:
    service = MCPApplicationService()

    tool = service.call_tool("news.unknown", {})
    resource = service.read_resource("news://unknown")

    assert tool.success is False
    assert tool.error_type == "MCPToolNotFound"
    assert resource.success is False
    assert resource.error_type == "MCPResourceNotFound"


def _raising_factory():
    raise AssertionError("factory should not be called")


class _FakeResearchService:
    def __init__(self) -> None:
        self.calls = []

    def analyze_paper(self, command):
        self.calls.append(("analyze_paper", command))
        return {
            "runId": command.run_id,
            "paperId": command.paper_id,
            "status": "succeeded",
            "analysisRef": "artifact://analysis",
        }

    def get_analysis(self, paper_id):
        self.calls.append(("get_analysis", paper_id))
        return {
            "runId": "research-run-1",
            "paperId": paper_id,
            "status": "succeeded",
            "analysis": {"summary": "Grounded analysis"},
        }

    def get_reader(self, paper_id):
        self.calls.append(("get_reader", paper_id))
        return {
            "paper": {"paperId": paper_id},
            "document": {"sections": []},
            "analysis": {"summary": "Grounded analysis"},
            "evidence": {"items": [{"evidenceId": "ev-1"}]},
            "navigation": [],
            "quality": [],
            "metadata": {"runId": "research-run-1"},
        }

    def ask_paper(self, paper_id, request):
        self.calls.append(("ask_paper", paper_id, request))
        return {
            "answer": "The method is evidence grounded.",
            "evidenceRefs": ["ev-1"],
            "confidence": 0.8,
        }

    def get_trace(self, run_id):
        self.calls.append(("get_trace", run_id))
        return {
            "runId": run_id,
            "paperId": "paper-1",
            "status": "succeeded",
            "trace": {"phases": ["PLAN", "EXECUTE", "VERIFY"]},
        }


class _FakeSourceService:
    def source_health(self, *, enabled_only):
        return _FakeResult(
            {
                "source_count": 1,
                "health": [{"source_id": "source-1", "status": "healthy"}],
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
                "items": [{"title": "Agent Runtime Evaluation"}],
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
                "items": [{"title": "Version 1.0.0"}],
                "errors": [],
            }
        )


class _FakeWorkerService:
    def __init__(self) -> None:
        self.calls = []
        self.queue_calls = []

    def list_worker_status(self, *, worker_id=None, stale_after_seconds=60):
        self.calls.append({"worker_id": worker_id, "stale_after_seconds": stale_after_seconds})
        return _FakeResult(
            {
                "worker_id": worker_id,
                "worker_count": 1,
                "unhealthy_count": 0,
                "stale_after_seconds": stale_after_seconds,
                "workers": [{"worker_id": "worker-1", "status": "running"}],
            }
        )

    def queue_status(self, *, queue_names=None):
        actual_queue_names = queue_names or ["news:queue:memory", "news:queue:sources"]
        self.queue_calls.append(actual_queue_names)
        return _FakeResult(
            {
                "queue_count": len(actual_queue_names),
                "total_stream_length": len(actual_queue_names),
                "total_pending_count": 0,
                "queues": [
                    {"queue_name": queue_name, "stream_length": 1, "pending_count": 0}
                    for queue_name in actual_queue_names
                ],
            }
        )


class _FakeResult:
    def __init__(self, payload) -> None:
        self.payload = payload

    def to_dict(self):
        return self.payload


@dataclass(frozen=True)
class _ReportRecord:
    report_id: str
    run_id: str
    title: str
    status: str
    report_json: dict
    report_markdown: str
    quality_score: float
    manifest_path: str

    def to_dict(self):
        return self.__dict__.copy()


def _write_report_run(root, run_id: str, title: str, body: str) -> None:
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "report.json").write_text(
        json.dumps({"title": title, "sections": [{"title": "Summary", "content": body}]}),
        encoding="utf-8",
    )
    (run_dir / "report.md").write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "workflow_id": "research-paper-analysis",
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
