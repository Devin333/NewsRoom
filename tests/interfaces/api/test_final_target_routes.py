from fastapi.testclient import TestClient

from interfaces.api import create_app
from interfaces.events import AuditEmitter, InMemoryAuditSink


def test_health_ready_and_dependencies_routes_use_common_envelope() -> None:
    client = TestClient(
        create_app(
            diagnostic_service_factory=lambda: _FakeDiagnosticService(),
            audit_emitter_factory=None,
        )
    )

    ready = client.get("/health/ready")
    dependencies = client.get("/health/dependencies")

    assert ready.status_code == 200
    assert ready.json()["data"]["ready"] is True
    assert dependencies.status_code == 200
    assert dependencies.json()["data"]["checks"][0]["check_id"] == "redis"


def test_report_markdown_quality_and_publish_request_routes() -> None:
    approval = _FakeApprovalService()
    client = TestClient(
        create_app(
            report_service_factory=lambda: _FakeReportService(),
            approval_service_factory=lambda: approval,
            audit_emitter_factory=None,
        )
    )

    markdown = client.get("/api/v1/reports/report-1/markdown")
    quality = client.get("/api/v1/reports/report-1/quality")
    publish = client.post(
        "/api/v1/reports/report-1/publish",
        json={"requested_by": "reviewer", "reason": "ship it"},
    )

    assert markdown.status_code == 200
    assert markdown.json()["data"]["markdown"] == "# Daily Intelligence"
    assert quality.json()["data"]["quality_score"] == 0.91
    assert publish.json()["data"]["status"] == "approval_required"
    assert approval.requests[0]["requested_action"] == "publish_report"


def test_source_detail_probe_artifact_alias_and_memory_document_routes() -> None:
    client = TestClient(
        create_app(
            source_service_factory=lambda: _FakeSourceService(),
            artifact_service_factory=lambda: _FakeArtifactService(),
            memory_service_factory=lambda: _FakeMemoryService(),
            audit_emitter_factory=None,
        )
    )

    source = client.get("/api/v1/sources/source-1")
    probe = client.post("/api/v1/sources/source-1/probe", json={"force": True})
    artifact = client.get("/api/v2/graph-runs/run-1/artifacts/output")
    memory = client.get("/api/v1/memory/doc-1?collection=report_sections")

    assert source.status_code == 200
    assert source.json()["data"]["source_id"] == "source-1"
    assert probe.json()["data"]["checked_count"] == 1
    assert artifact.json()["data"]["artifact_key"] == "output"
    assert memory.json()["data"]["document"]["document_id"] == "doc-1"


def test_api_audit_emits_redacted_record_for_request() -> None:
    sink = InMemoryAuditSink()
    client = TestClient(
        create_app(
            report_service_factory=lambda: _FakeReportService(),
            audit_emitter_factory=lambda: AuditEmitter(sink),
        )
    )

    response = client.get(
        "/api/v1/reports/latest?api_key=hidden",
        headers={"X-News-Actor": "operator-1", "X-News-Roles": "operator"},
    )

    assert response.status_code == 200
    assert sink.records[0].actor.actor_id == "operator-1"
    assert sink.records[0].resource_type == "reports"
    assert sink.records[0].result == "succeeded"
    assert sink.records[0].metadata["query"]["api_key"] == "[redacted]"


def test_api_audit_emits_write_record_for_research_request() -> None:
    sink = InMemoryAuditSink()
    research = _FakeResearchService()
    client = TestClient(
        create_app(
            research_service_factory=lambda: research,
            audit_emitter_factory=lambda: AuditEmitter(sink),
        )
    )

    response = client.post(
        "/api/v1/research/papers/analyze?api_key=hidden",
        json={
            "paperId": "paper-1",
            "sourceUrl": "https://arxiv.org/abs/2401.00001",
            "runId": "run-audit",
        },
        headers={"X-Request-ID": "write-audit", "X-News-Actor": "operator-1"},
    )

    assert response.status_code == 200
    assert sink.records[0].action == "api_request_post"
    assert sink.records[0].actor.actor_id == "operator-1"
    assert sink.records[0].actor.request_id == "write-audit"
    assert sink.records[0].resource_type == "research"
    assert sink.records[0].resource_id == "papers"
    assert sink.records[0].result == "succeeded"
    assert sink.records[0].metadata["method"] == "POST"
    assert sink.records[0].metadata["query"]["api_key"] == "[redacted]"


class _FakeResearchService:
    def analyze_paper(self, request):
        return {
            "runId": request.run_id or "research-run-1",
            "paperId": request.paper_id,
            "status": "succeeded",
            "analysisRef": f"artifact://{request.run_id or 'research-run-1'}/analysis",
        }


class _FakeDiagnosticService:
    def run(self):
        return _FakeResult(
            {
                "status": "ok",
                "summary": "1 ok",
                "checks": [{"check_id": "redis", "status": "ok"}],
            }
        )


class _FakeReportService:
    def latest_report(self):
        return _FakeReport()

    def get_report(self, report_id):
        return _FakeReport(report_id=report_id)

    def report_markdown(self, report_id):
        return _FakeResult({"report_id": report_id, "run_id": "run-1", "markdown": "# Daily Intelligence"})

    def report_quality(self, report_id):
        return _FakeResult(
            {
                "report_id": report_id,
                "run_id": "run-1",
                "status": "final",
                "quality_score": 0.91,
                "quality": {"citation_coverage_score": 1.0},
            }
        )

    def publish_report(self, report_id, **kwargs):
        return _FakeAction(
            {
                "action": "publish_report",
                "resource_type": "report",
                "resource_id": report_id,
                "status": "approval_required",
                "message": "approval required",
                "metadata": kwargs,
            }
        )


class _FakeReport:
    def __init__(self, report_id="report-1") -> None:
        self.report_id = report_id
        self.run_id = "run-1"
        self.status = "final"
        self.title = "Daily Intelligence"
        self.report_json = {"quality": {"citation_coverage_score": 1.0}}
        self.report_markdown = "# Daily Intelligence"
        self.quality_score = 0.91
        self.manifest_path = ".newsroom/runs/run-1/manifest.json"


class _FakeApprovalService:
    def __init__(self) -> None:
        self.requests = []

    def submit_request(self, **kwargs):
        self.requests.append(kwargs)
        return _FakeResult({"approval_id": "approval-1", "approval": kwargs})


class _FakeSourceService:
    def get_source(self, source_id):
        return _FakeResult(
            {
                "source_id": source_id,
                "source": {"source_id": source_id, "name": "Source"},
                "name": "Source",
            }
        )

    def check_source_health(self, **kwargs):
        return _FakeResult(
            {
                "checked_count": 1,
                "succeeded_count": 1,
                "failed_count": 0,
                "skipped_count": 0,
                "entries": [{"source_id": kwargs["source_id"], "ok": True}],
            }
        )


class _FakeArtifactService:
    def get_artifact(self, run_id, artifact_key):
        return _FakeResult(
            {
                "run_id": run_id,
                "artifact_key": artifact_key,
                "relative_path": "output.json",
                "content_type": "application/json",
                "size_bytes": 2,
                "content": {},
            }
        )


class _FakeMemoryService:
    def get_document(self, document_id, *, collection):
        return _FakeResult(
            {
                "collection": collection,
                "document_id": document_id,
                "document": {
                    "document_id": document_id,
                    "score": 1.0,
                    "text": "memory",
                    "source_type": "report_section",
                    "payload": {},
                    "run_id": "run-1",
                    "report_id": "report-1",
                    "evidence_id": None,
                    "source_item_id": None,
                },
            }
        )


class _FakeResult:
    def __init__(self, payload) -> None:
        self.payload = payload

    def to_dict(self):
        return self.payload


class _FakeAction(_FakeResult):
    pass
