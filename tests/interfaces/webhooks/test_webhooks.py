import json
import urllib.error

from interfaces.webhooks import (
    IncomingWebhookHandler,
    OutgoingWebhookClient,
    OutgoingWebhookDeadLetter,
    build_signature_header,
    verify_signature,
)


def test_webhook_signature_verification() -> None:
    body = b'{"event_type":"manual.daily_run"}'
    signature = build_signature_header(body, "secret")

    assert verify_signature(body, "secret", signature) is True
    assert verify_signature(body, "secret", "sha256=wrong") is False


def test_incoming_webhook_manual_daily_run_enqueues_worker_task() -> None:
    body = json.dumps({"topic": "AI policy", "source_limit": 2}).encode("utf-8")
    handler = IncomingWebhookHandler(secret="secret", worker_service=_FakeWorkerService())
    event = handler.parse(
        body,
        event_type="manual.daily_run",
        signature_header=build_signature_header(body, "secret"),
    )

    result = handler.handle(event)

    assert event.signature_verified is True
    assert result["handled"] is True
    assert result["result"]["topic"] == "AI policy"


def test_outgoing_webhook_signs_json_request() -> None:
    opener = _FakeOpener()
    client = OutgoingWebhookClient(secret="secret", opener=opener)

    result = client.send("https://hooks.example/news", "report.published", {"report_id": "r1"})

    assert result.success is True
    assert result.to_dict()["attempt_count"] == 1
    assert result.to_dict()["dead_lettered"] is False
    assert opener.request.headers["X-news-event-type"] == "report.published"
    assert opener.request.headers["X-news-signature"].startswith("sha256=")


def test_outgoing_webhook_retries_until_success() -> None:
    opener = _SequenceOpener([_FakeResponse(status=503, body=b"busy"), _FakeResponse(status=202)])
    client = OutgoingWebhookClient(secret="secret", opener=opener, max_attempts=3)

    result = client.send("https://hooks.example/news", "report.published", {"report_id": "r1"})
    payload = result.to_dict()

    assert result.success is True
    assert payload["attempt_count"] == 2
    assert payload["attempts"][0]["status_code"] == 503
    assert payload["attempts"][1]["status_code"] == 202
    assert payload["dead_lettered"] is False


def test_outgoing_webhook_dead_letters_after_failed_retries() -> None:
    dead_letters: list[OutgoingWebhookDeadLetter] = []
    opener = _SequenceOpener([RuntimeError("network token leak"), _FakeResponse(status=500)])
    client = OutgoingWebhookClient(
        secret="secret",
        opener=opener,
        max_attempts=2,
        dead_letter_sink=dead_letters.append,
    )

    result = client.send(
        "https://hooks.example/news",
        "report.published",
        {"report_id": "r1", "api_key": "hidden"},
    )
    payload = result.to_dict()
    dead_letter = dead_letters[0].to_dict()

    assert result.success is False
    assert payload["attempt_count"] == 2
    assert payload["dead_lettered"] is True
    assert dead_letter["reason"] == "HTTP 500"
    assert dead_letter["payload"]["api_key"] == "[redacted]"
    assert dead_letter["attempts"][0]["error_type"] == "RuntimeError"


def test_outgoing_webhook_records_http_error_status_attempt() -> None:
    dead_letters: list[OutgoingWebhookDeadLetter] = []
    opener = _SequenceOpener(
        [
            urllib.error.HTTPError(
                "https://hooks.example/news",
                429,
                "Too Many Requests",
                hdrs=None,
                fp=_FakeErrorBody(b"retry later"),
            )
        ]
    )
    client = OutgoingWebhookClient(opener=opener, max_attempts=1, dead_letter_sink=dead_letters.append)

    result = client.send("https://hooks.example/news", "report.published", {"report_id": "r1"})
    payload = result.to_dict()

    assert result.success is False
    assert payload["status_code"] == 429
    assert payload["attempts"][0]["status_code"] == 429
    assert payload["attempts"][0]["response_body"] == "retry later"
    assert dead_letters[0].reason == "HTTPError: HTTP Error 429: Too Many Requests"


class _FakeWorkerService:
    def enqueue_daily(self, **kwargs):
        return _FakeResult(
            {
                "task_id": "task-1",
                "status": "queued",
                "topic": kwargs["topic"],
                "source_limit": kwargs["source_limit"],
            }
        )


class _FakeResult:
    def __init__(self, payload) -> None:
        self.payload = payload

    def to_dict(self):
        return self.payload


class _FakeOpener:
    def __call__(self, request, timeout):
        self.request = request
        return _FakeResponse()


class _FakeResponse:
    def __init__(self, *, status=202, body=b"accepted") -> None:
        self.status = status
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


class _SequenceOpener:
    def __init__(self, outcomes) -> None:
        self.outcomes = list(outcomes)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FakeErrorBody:
    def __init__(self, body) -> None:
        self.body = body

    def read(self):
        return self.body

    def close(self):
        return None
