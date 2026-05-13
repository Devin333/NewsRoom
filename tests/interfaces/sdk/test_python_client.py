import json
import urllib.error

from interfaces.sdk import NewsApiError, NewsClient


def test_news_client_posts_daily_run_with_api_envelope() -> None:
    opener = _FakeOpener(
        {
            "success": True,
            "data": {"run_id": "run-1", "status": "queued"},
            "request_id": "req-1",
            "schema_version": "1.0",
        }
    )
    client = NewsClient("https://news.example", api_key="token", opener=opener)

    result = client.runs.create_daily(topic="AI policy", source_limit=2)

    assert result["status"] == "queued"
    assert opener.requests[0].full_url == "https://news.example/api/v1/runs"
    assert opener.requests[0].headers["Authorization"] == "Bearer token"
    assert json.loads(opener.requests[0].data.decode("utf-8"))["topic"] == "AI policy"


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
