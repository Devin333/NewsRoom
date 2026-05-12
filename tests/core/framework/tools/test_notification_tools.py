import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from xml.etree import ElementTree

from core.framework.tools import (
    ToolCall,
    ToolExecutor,
    ToolPolicy,
    ToolRegistry,
    ToolStatus,
    register_notification_tools,
)


def test_notification_webhook_tool_posts_json_to_allowed_domain() -> None:
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            received.append(
                {
                    "path": self.path,
                    "content_type": self.headers["Content-Type"],
                    "body": self.rfile.read(length).decode("utf-8"),
                }
            )
            self.send_response(202)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, format, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        registry = ToolRegistry()
        register_notification_tools(
            registry,
            allowed_webhook_domains=["127.0.0.1"],
        )
        executor = ToolExecutor(registry)
        url = f"http://127.0.0.1:{server.server_port}/hook?token=not-returned"

        observation = executor.execute(
            ToolCall(
                tool_name="notification.webhook",
                arguments={
                    "url": url,
                    "payload": {"event": "report_ready", "report_id": "run-1:final"},
                    "headers": {"X-News-Run": "run-1"},
                },
            ),
            ToolPolicy(
                allowed_tools=["notification.webhook"],
                require_approval_for_side_effects=False,
            ),
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["sent"] is True
    assert observation.result.output["status_code"] == 202
    assert observation.result.output["url"] == f"http://127.0.0.1:{server.server_port}/hook"
    assert observation.result.output["response_preview"] == '{"ok":true}'
    assert received[0]["path"] == "/hook?token=not-returned"
    assert received[0]["content_type"] == "application/json"
    assert json.loads(received[0]["body"]) == {
        "event": "report_ready",
        "report_id": "run-1:final",
    }


def test_notification_webhook_tool_requires_approval_by_default() -> None:
    calls = {"count": 0}

    def sender(url, body, headers, timeout_seconds):
        calls["count"] += 1
        return {"status_code": 200}

    registry = ToolRegistry()
    register_notification_tools(
        registry,
        allowed_webhook_domains=["example.com"],
        webhook_sender=sender,
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="notification.webhook",
            arguments={"url": "https://example.com/hook", "payload": {"ok": True}},
        ),
        ToolPolicy(allowed_tools=["notification.webhook"]),
    )

    assert observation.status == ToolStatus.APPROVAL_REQUIRED
    assert calls["count"] == 0


def test_notification_webhook_tool_blocks_domains_outside_allowlist_before_send() -> None:
    calls = {"count": 0}

    def sender(url, body, headers, timeout_seconds):
        calls["count"] += 1
        return {"status_code": 200}

    registry = ToolRegistry()
    register_notification_tools(
        registry,
        allowed_webhook_domains=["example.com"],
        webhook_sender=sender,
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="notification.webhook",
            arguments={"url": "https://evil.test/hook", "payload": {"ok": True}},
        ),
        ToolPolicy(
            allowed_tools=["notification.webhook"],
            require_approval_for_side_effects=False,
        ),
    )

    assert observation.status == ToolStatus.FAILED
    assert calls["count"] == 0
    assert "allowed domains" in (observation.result.error_message or "")


def test_notification_webhook_tool_rejects_secret_headers_before_send() -> None:
    calls = {"count": 0}

    def sender(url, body, headers, timeout_seconds):
        calls["count"] += 1
        return {"status_code": 200}

    registry = ToolRegistry()
    register_notification_tools(
        registry,
        allowed_webhook_domains=["example.com"],
        webhook_sender=sender,
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="notification.webhook",
            arguments={
                "url": "https://example.com/hook",
                "payload": {"ok": True},
                "headers": {"Authorization": "Bearer hidden"},
            },
        ),
        ToolPolicy(
            allowed_tools=["notification.webhook"],
            require_approval_for_side_effects=False,
        ),
    )

    assert observation.status == ToolStatus.FAILED
    assert calls["count"] == 0
    assert "header is not allowed" in (observation.result.error_message or "")


def test_notification_slack_tool_posts_json_to_configured_webhook_without_leaking_url() -> None:
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            received.append(
                {
                    "path": self.path,
                    "content_type": self.headers["Content-Type"],
                    "body": self.rfile.read(length).decode("utf-8"),
                }
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, format, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        registry = ToolRegistry()
        register_notification_tools(
            registry,
            allowed_slack_domains=["127.0.0.1"],
            slack_webhook_url=(
                f"http://127.0.0.1:{server.server_port}/services/T000/B000/SECRET"
            ),
        )
        executor = ToolExecutor(registry)

        observation = executor.execute(
            ToolCall(
                tool_name="notification.slack",
                arguments={
                    "text": "Daily report ready",
                    "blocks": [
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": "*Daily report ready*"},
                        }
                    ],
                    "timeout_seconds": 3,
                },
            ),
            ToolPolicy(
                allowed_tools=["notification.slack"],
                require_approval_for_side_effects=False,
            ),
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    output_text = json.dumps(observation.result.output, sort_keys=True)

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["sent"] is True
    assert observation.result.output["host"] == "127.0.0.1"
    assert observation.result.output["status_code"] == 200
    assert observation.result.output["response_preview"] == "ok"
    assert "SECRET" not in output_text
    assert "/services/" not in output_text
    assert received[0]["path"] == "/services/T000/B000/SECRET"
    assert received[0]["content_type"] == "application/json"
    assert json.loads(received[0]["body"]) == {
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Daily report ready*"},
            }
        ],
        "text": "Daily report ready",
    }


def test_notification_slack_tool_requires_approval_by_default() -> None:
    calls = {"count": 0}

    def sender(url, body, headers, timeout_seconds):
        calls["count"] += 1
        return {"status_code": 200}

    registry = ToolRegistry()
    register_notification_tools(
        registry,
        slack_webhook_url="https://hooks.slack.com/services/T000/B000/SECRET",
        slack_sender=sender,
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="notification.slack",
            arguments={"text": "Daily report ready"},
        ),
        ToolPolicy(allowed_tools=["notification.slack"]),
    )

    assert observation.status == ToolStatus.APPROVAL_REQUIRED
    assert calls["count"] == 0


def test_notification_slack_tool_blocks_domains_outside_allowlist_before_send() -> None:
    calls = {"count": 0}

    def sender(url, body, headers, timeout_seconds):
        calls["count"] += 1
        return {"status_code": 200}

    registry = ToolRegistry()
    register_notification_tools(
        registry,
        allowed_slack_domains=["hooks.slack.com"],
        slack_webhook_url="https://hooks.evil.test/services/T000/B000/SECRET",
        slack_sender=sender,
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="notification.slack",
            arguments={"text": "Daily report ready"},
        ),
        ToolPolicy(
            allowed_tools=["notification.slack"],
            require_approval_for_side_effects=False,
        ),
    )

    assert observation.status == ToolStatus.FAILED
    assert calls["count"] == 0
    assert "host is not in allowed domains" in (observation.result.error_message or "")


def test_notification_slack_tool_requires_message_content_before_send() -> None:
    calls = {"count": 0}

    def sender(url, body, headers, timeout_seconds):
        calls["count"] += 1
        return {"status_code": 200}

    registry = ToolRegistry()
    register_notification_tools(
        registry,
        slack_webhook_url="https://hooks.slack.com/services/T000/B000/SECRET",
        slack_sender=sender,
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(tool_name="notification.slack", arguments={}),
        ToolPolicy(
            allowed_tools=["notification.slack"],
            require_approval_for_side_effects=False,
        ),
    )

    assert observation.status == ToolStatus.FAILED
    assert calls["count"] == 0
    assert "text, blocks, or attachments is required" in (
        observation.result.error_message or ""
    )


def test_notification_email_tool_sends_mime_message_to_allowed_domain() -> None:
    sender = _CapturingEmailSender()
    registry = ToolRegistry()
    register_notification_tools(
        registry,
        allowed_email_domains=["example.com"],
        email_from_address="newsroom@example.com",
        email_sender=sender,
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="notification.email",
            arguments={
                "to": ["Editor <editor@example.com>"],
                "cc": ["desk@example.com"],
                "bcc": ["audit@example.com"],
                "subject": "Daily report ready",
                "text_body": "The daily report is ready.",
                "html_body": "<p>The daily report is ready.</p>",
                "reply_to": "replies@example.com",
                "timeout_seconds": 3,
            },
        ),
        ToolPolicy(
            allowed_tools=["notification.email"],
            require_approval_for_side_effects=False,
        ),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["sent"] is True
    assert observation.result.output["from"] == "newsroom@example.com"
    assert observation.result.output["to"] == ["editor@example.com"]
    assert observation.result.output["cc"] == ["desk@example.com"]
    assert observation.result.output["bcc_count"] == 1
    assert observation.result.output["accepted_count"] == 3
    assert observation.result.output["refused_count"] == 0
    assert sender.recipients == ["editor@example.com", "desk@example.com", "audit@example.com"]
    assert sender.timeout_seconds == 3.0
    assert sender.message["From"] == "newsroom@example.com"
    assert sender.message["To"] == "editor@example.com"
    assert sender.message["Cc"] == "desk@example.com"
    assert sender.message["Reply-To"] == "replies@example.com"
    assert sender.message["Subject"] == "Daily report ready"
    assert sender.message["Bcc"] is None
    assert sender.message.get_body(("plain",)).get_content().strip() == (
        "The daily report is ready."
    )
    assert sender.message.get_body(("html",)).get_content().strip() == (
        "<p>The daily report is ready.</p>"
    )


def test_notification_email_tool_requires_approval_by_default() -> None:
    sender = _CapturingEmailSender()
    registry = ToolRegistry()
    register_notification_tools(
        registry,
        allowed_email_domains=["example.com"],
        email_from_address="newsroom@example.com",
        email_sender=sender,
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="notification.email",
            arguments={
                "to": ["editor@example.com"],
                "subject": "Daily report ready",
                "text_body": "Ready.",
            },
        ),
        ToolPolicy(allowed_tools=["notification.email"]),
    )

    assert observation.status == ToolStatus.APPROVAL_REQUIRED
    assert sender.message is None


def test_notification_email_tool_blocks_domains_outside_allowlist_before_send() -> None:
    sender = _CapturingEmailSender()
    registry = ToolRegistry()
    register_notification_tools(
        registry,
        allowed_email_domains=["example.com"],
        email_from_address="newsroom@example.com",
        email_sender=sender,
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="notification.email",
            arguments={
                "to": ["editor@outside.test"],
                "subject": "Daily report ready",
                "text_body": "Ready.",
            },
        ),
        ToolPolicy(
            allowed_tools=["notification.email"],
            require_approval_for_side_effects=False,
        ),
    )

    assert observation.status == ToolStatus.FAILED
    assert sender.message is None
    assert "recipient domain is not allowed" in (observation.result.error_message or "")


def test_notification_email_tool_requires_body_before_send() -> None:
    sender = _CapturingEmailSender()
    registry = ToolRegistry()
    register_notification_tools(
        registry,
        allowed_email_domains=["example.com"],
        email_from_address="newsroom@example.com",
        email_sender=sender,
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="notification.email",
            arguments={
                "to": ["editor@example.com"],
                "subject": "Daily report ready",
            },
        ),
        ToolPolicy(
            allowed_tools=["notification.email"],
            require_approval_for_side_effects=False,
        ),
    )

    assert observation.status == ToolStatus.FAILED
    assert sender.message is None
    assert "text_body or html_body is required" in (observation.result.error_message or "")


def test_notification_rss_publish_tool_writes_configured_feed_item(tmp_path) -> None:
    feed_path = tmp_path / "feeds" / "news.xml"
    registry = ToolRegistry()
    register_notification_tools(
        registry,
        rss_feed_path=feed_path,
        rss_feed_title="NewsRoom Feed",
        rss_feed_link="https://example.com/feed",
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="notification.rss_publish",
            arguments={
                "title": "Daily report ready",
                "link": "https://example.com/reports/run-1",
                "description": "A report was published.",
                "guid": "run-1:final",
                "published_at": "2026-05-12T00:00:00Z",
            },
        ),
        ToolPolicy(
            allowed_tools=["notification.rss_publish"],
            require_approval_for_side_effects=False,
        ),
    )

    root = ElementTree.parse(feed_path).getroot()
    channel = root.find("channel")
    item = channel.find("item")

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["published"] is True
    assert observation.result.output["item_count"] == 1
    assert channel.findtext("title") == "NewsRoom Feed"
    assert item.findtext("title") == "Daily report ready"
    assert item.findtext("link") == "https://example.com/reports/run-1"
    assert item.findtext("guid") == "run-1:final"
    assert item.findtext("pubDate") == "Tue, 12 May 2026 00:00:00 GMT"


def test_notification_rss_publish_tool_requires_approval_by_default(tmp_path) -> None:
    feed_path = tmp_path / "feeds" / "news.xml"
    registry = ToolRegistry()
    register_notification_tools(registry, rss_feed_path=feed_path)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="notification.rss_publish",
            arguments={
                "title": "Daily report ready",
                "link": "https://example.com/reports/run-1",
            },
        ),
        ToolPolicy(allowed_tools=["notification.rss_publish"]),
    )

    assert observation.status == ToolStatus.APPROVAL_REQUIRED
    assert not feed_path.exists()


class _CapturingEmailSender:
    def __init__(self) -> None:
        self.message = None
        self.recipients = []
        self.timeout_seconds = None

    def __call__(self, message, recipients, timeout_seconds):
        self.message = message
        self.recipients = list(recipients)
        self.timeout_seconds = timeout_seconds
        return {
            "accepted_recipients": list(recipients),
            "refused_recipients": [],
        }
