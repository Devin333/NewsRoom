import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

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
