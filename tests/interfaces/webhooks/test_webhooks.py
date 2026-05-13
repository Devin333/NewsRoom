import json

from interfaces.webhooks import (
    IncomingWebhookHandler,
    OutgoingWebhookClient,
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
    assert opener.request.headers["X-news-event-type"] == "report.published"
    assert opener.request.headers["X-news-signature"].startswith("sha256=")


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
    status = 202

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return b"accepted"
