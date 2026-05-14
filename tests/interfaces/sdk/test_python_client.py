import json
import urllib.error

from interfaces.sdk import NewsApiError, NewsClient


def test_news_client_posts_daily_run_with_api_envelope() -> None:
    opener = _FakeOpener(
        {
            "success": True,
            "data": {
                "run_id": "run-1",
                "task_id": "task-1",
                "status": "queued",
                "task_status": "queued",
                "run_status": None,
                "report_status": None,
            },
            "request_id": "req-1",
            "schema_version": "1.0",
        }
    )
    client = NewsClient("https://news.example", api_key="token", opener=opener)

    result = client.runs.create_daily(topic="AI policy", source_limit=2)

    assert result["status"] == "queued"
    assert result["task_status"] == "queued"
    assert result["run_status"] is None
    assert result["report_status"] is None
    assert opener.requests[0].full_url == "https://news.example/api/v1/runs"
    assert opener.requests[0].headers["Authorization"] == "Bearer token"
    assert json.loads(opener.requests[0].data.decode("utf-8"))["topic"] == "AI policy"


def test_news_client_reads_run_inspection_endpoints() -> None:
    opener = _FakeOpener(
        {
            "success": True,
            "data": {"ok": True},
            "request_id": "req-1",
            "schema_version": "1.0",
        }
    )
    client = NewsClient("https://news.example", opener=opener)

    assert client.runs.get("run/1") == {"ok": True}
    assert client.runs.manifest("run/1") == {"ok": True}
    assert client.runs.events("run/1", limit=2) == {"ok": True}
    assert client.runs.replay("run/1") == {"ok": True}
    assert client.runs.diagnostics("run/1") == {"ok": True}
    assert client.runs.health("run/1") == {"ok": True}
    assert client.runs.catalog_health() == {"ok": True}
    assert client.runs.compare("run/1", "run 2") == {"ok": True}

    assert [request.full_url for request in opener.requests] == [
        "https://news.example/api/v1/runs/run%2F1",
        "https://news.example/api/v1/runs/run%2F1/manifest",
        "https://news.example/api/v1/runs/run%2F1/events?limit=2",
        "https://news.example/api/v1/runs/run%2F1/replay",
        "https://news.example/api/v1/runs/run%2F1/diagnostics",
        "https://news.example/api/v1/runs/run%2F1/health",
        "https://news.example/api/v1/runs/catalog/health",
        "https://news.example/api/v1/runs/compare?base_run_id=run%2F1&target_run_id=run+2",
    ]


def test_news_client_reads_p1_p2_interface_surfaces() -> None:
    opener = _FakeOpener(
        {
            "success": True,
            "data": {"ok": True},
            "request_id": "req-1",
            "schema_version": "1.0",
        }
    )
    client = NewsClient("https://news.example", opener=opener)

    assert client.mcp.catalog() == {"ok": True}
    assert client.mcp.capabilities() == {"ok": True}
    assert client.workers.list(stale_after_seconds=30) == {"ok": True}
    assert client.workers.get("worker/1", stale_after_seconds=45) == {"ok": True}
    assert client.workers.queues(queue_names=["news:queue:daily", "custom"]) == {"ok": True}
    assert client.storage.metrics() == {"ok": True}
    assert client.storage.retention_plan(run_id="run/1", report_retention_days=7) == {"ok": True}
    assert client.sources.list(include_disabled=True) == {"ok": True}
    assert client.sources.health(include_disabled=True) == {"ok": True}
    assert client.sources.validation() == {"ok": True}
    assert client.sources.get("source/1") == {"ok": True}
    assert client.schedules.list(include_disabled=True) == {"ok": True}
    assert client.approvals.list(status="pending") == {"ok": True}
    assert client.approvals.get("approval/1") == {"ok": True}

    assert [request.full_url for request in opener.requests] == [
        "https://news.example/api/v1/mcp/catalog",
        "https://news.example/api/v1/mcp/capabilities",
        "https://news.example/api/v1/workers?stale_after_seconds=30",
        "https://news.example/api/v1/workers/worker%2F1?stale_after_seconds=45",
        "https://news.example/api/v1/queues?queue_name=news%3Aqueue%3Adaily&queue_name=custom",
        "https://news.example/api/v1/storage/metrics",
        "https://news.example/api/v1/storage/retention/plan?run_id=run%2F1&report_retention_days=7",
        "https://news.example/api/v1/sources?include_disabled=True",
        "https://news.example/api/v1/sources/health?include_disabled=True",
        "https://news.example/api/v1/sources/validation",
        "https://news.example/api/v1/sources/source%2F1",
        "https://news.example/api/v1/schedules?include_disabled=True",
        "https://news.example/api/v1/approvals?status=pending",
        "https://news.example/api/v1/approvals/approval%2F1",
    ]


def test_news_client_writes_extended_interface_surfaces() -> None:
    opener = _FakeOpener(
        {
            "success": True,
            "data": {"ok": True},
            "request_id": "req-1",
            "schema_version": "1.0",
        }
    )
    client = NewsClient("https://news.example", opener=opener)

    assert client.memory.reindex("run/1", topic="AI policy") == {"ok": True}
    assert client.sources.probe("source/1", force=True, include_disabled=True, limit=2) == {"ok": True}
    assert client.sources.fetch_arxiv("cat:cs.AI", limit=1) == {"ok": True}
    assert client.sources.fetch_github_releases("owner/repo", limit=1) == {"ok": True}
    assert client.schedules.trigger("schedule/1", now="2026-05-14T00:00:00Z") == {"ok": True}
    assert client.approvals.approve("approval/1", decided_by="reviewer", reason="ok") == {"ok": True}
    assert client.approvals.reject("approval/2", decided_by="reviewer") == {"ok": True}
    assert client.approvals.resume_context("approval/3", decision_key="editor_decision") == {"ok": True}

    assert [request.full_url for request in opener.requests] == [
        "https://news.example/api/v1/memory/reindex",
        "https://news.example/api/v1/sources/source%2F1/probe",
        "https://news.example/api/v1/sources/arxiv/fetch",
        "https://news.example/api/v1/sources/github/releases",
        "https://news.example/api/v1/schedules/schedule%2F1/trigger",
        "https://news.example/api/v1/approvals/approval%2F1/approve",
        "https://news.example/api/v1/approvals/approval%2F2/reject",
        "https://news.example/api/v1/approvals/approval%2F3/resume-context",
    ]
    assert [json.loads(request.data.decode("utf-8")) for request in opener.requests] == [
        {"run_id": "run/1", "topic": "AI policy"},
        {"force": True, "include_disabled": True, "limit": 2},
        {"query": "cat:cs.AI", "limit": 1},
        {"repository": "owner/repo", "limit": 1},
        {"now": "2026-05-14T00:00:00Z"},
        {"decided_by": "reviewer", "reason": "ok"},
        {"decided_by": "reviewer", "reason": None},
        {"decision_key": "editor_decision"},
    ]


def test_news_client_reads_report_memory_and_artifact_helpers() -> None:
    opener = _FakeOpener(
        {
            "success": True,
            "data": {"ok": True},
            "request_id": "req-1",
            "schema_version": "1.0",
        }
    )
    client = NewsClient("https://news.example", opener=opener)

    assert client.reports.list(limit=1, workflow_id="daily") == {"ok": True}
    assert client.reports.markdown("report/1") == {"ok": True}
    assert client.reports.quality("report/1") == {"ok": True}
    assert client.memory.get("doc/1", collection="reports") == {"ok": True}
    assert client.runs.lineage("run/1") == {"ok": True}
    assert client.runs.lineage_upstream("run/1", target_type="report", target_id="r1") == {"ok": True}
    assert client.runs.lineage_downstream("run/1", source_type="source", source_id="s1") == {"ok": True}
    assert client.runs.artifacts("run/1") == {"ok": True}
    assert client.runs.artifact("run/1", "report/json") == {"ok": True}

    assert [request.full_url for request in opener.requests] == [
        "https://news.example/api/v1/reports?limit=1&workflow_id=daily",
        "https://news.example/api/v1/reports/report%2F1/markdown",
        "https://news.example/api/v1/reports/report%2F1/quality",
        "https://news.example/api/v1/memory/doc%2F1?collection=reports",
        "https://news.example/api/v1/runs/run%2F1/lineage",
        "https://news.example/api/v1/runs/run%2F1/lineage/upstream?target_type=report&target_id=r1",
        "https://news.example/api/v1/runs/run%2F1/lineage/downstream?source_type=source&source_id=s1",
        "https://news.example/api/v1/runs/run%2F1/artifacts",
        "https://news.example/api/v1/runs/run%2F1/artifacts/report%2Fjson",
    ]


def test_news_client_raises_typed_api_error() -> None:
    client = NewsClient(
        "https://news.example",
        opener=_HttpErrorOpener(
            {
                "success": False,
                "error": {
                    "code": "report_not_found",
                    "message": "missing",
                    "details": {"report_id": "missing"},
                    "retryable": False,
                    "user_action_required": True,
                    "request_id": "req-error",
                },
                "request_id": "req-1",
                "schema_version": "1.0",
            },
            status_code=404,
        ),
    )

    try:
        client.reports.get("missing")
    except NewsApiError as exc:
        assert exc.code == "report_not_found"
        assert exc.status_code == 404
        assert exc.details == {"report_id": "missing"}
        assert exc.retryable is False
        assert exc.user_action_required is True
        assert exc.request_id == "req-error"
    else:
        raise AssertionError("NewsApiError was not raised")


def test_news_client_raises_error_from_success_false_envelope() -> None:
    client = NewsClient(
        "https://news.example",
        opener=_FakeOpener(
            {
                "success": False,
                "error": {
                    "code": "invalid_request",
                    "message": "invalid source_limit",
                    "details": {"field": "source_limit"},
                    "retryable": True,
                    "user_action_required": False,
                },
                "request_id": "req-envelope",
                "schema_version": "1.0",
            }
        ),
    )

    try:
        client.runs.create_daily(source_limit=0)
    except NewsApiError as exc:
        assert exc.code == "invalid_request"
        assert exc.status_code == 200
        assert exc.details == {"field": "source_limit"}
        assert exc.retryable is True
        assert exc.user_action_required is False
        assert exc.request_id == "req-envelope"
    else:
        raise AssertionError("NewsApiError was not raised")


class _FakeOpener:
    def __init__(self, payload) -> None:
        self.payload = payload
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        return _FakeResponse(self.payload)


class _HttpErrorOpener:
    def __init__(self, payload, *, status_code) -> None:
        self.payload = payload
        self.status_code = status_code

    def __call__(self, request, timeout):
        raise urllib.error.HTTPError(
            request.full_url,
            self.status_code,
            "error",
            hdrs=None,
            fp=_ErrorBody(self.payload),
        )


class _FakeResponse:
    status = 200

    def __init__(self, payload) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class _ErrorBody:
    def __init__(self, payload) -> None:
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def close(self):
        return None
