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
