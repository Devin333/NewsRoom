from __future__ import annotations

import json
from typing import Any, Callable
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from core.framework.tools.models import ToolDefinition
from core.framework.tools.registry import ToolRegistry


WebhookSender = Callable[[str, bytes, dict[str, str], float], dict[str, Any]]
_SECRET_HEADER_NAMES = {"authorization", "cookie", "x-api-key", "api-key"}


def register_notification_tools(
    registry: ToolRegistry,
    *,
    allowed_webhook_domains: list[str] | None = None,
    webhook_sender: WebhookSender | None = None,
) -> None:
    allowed_domain_tuple = _allowed_domains(allowed_webhook_domains)
    sender = webhook_sender or _default_webhook_sender
    registry.register(
        ToolDefinition(
            name="notification.webhook",
            description="Send a JSON webhook notification to an allowed HTTP(S) endpoint.",
            input_schema={
                "required": ["url", "payload"],
                "properties": {
                    "url": {"type": "string"},
                    "payload": {"type": "object"},
                    "headers": {"type": "object"},
                    "timeout_seconds": {"type": "number"},
                },
                "additionalProperties": False,
            },
            side_effect="writes_external_state",
            requires_approval=True,
            concurrency_safe=False,
            max_result_bytes=100_000,
            metadata={"notification_channel": "webhook"},
        ),
        lambda args: _send_webhook(
            args,
            allowed_domains=allowed_domain_tuple,
            sender=sender,
        ),
    )


def _send_webhook(
    args: dict[str, Any],
    *,
    allowed_domains: tuple[str, ...],
    sender: WebhookSender,
) -> dict[str, Any]:
    url = str(args["url"]).strip()
    if not url:
        raise ValueError("url is required")
    _ensure_http_url(url)
    _ensure_allowed_domain(url, allowed_domains)
    payload = args["payload"]
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    headers = _headers(args.get("headers"))
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    response = sender(url, body, headers, _timeout(args.get("timeout_seconds")))
    return {
        "sent": True,
        "url": _url_without_query(url),
        "status_code": response.get("status_code"),
        "content_type": response.get("content_type"),
        "response_preview": str(response.get("response_text") or "")[:500],
        "payload_bytes": len(body),
    }


def _default_webhook_sender(
    url: str,
    body: bytes,
    headers: dict[str, str],
    timeout_seconds: float,
) -> dict[str, Any]:
    request = Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "NewsRoomToolRuntime/1.0",
            **headers,
        },
        method="POST",
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        response_body = response.read(10_000)
        response_headers = getattr(response, "headers", None)
        return {
            "status_code": getattr(response, "status", None),
            "content_type": (
                response_headers.get_content_type() if response_headers is not None else None
            ),
            "response_text": response_body.decode("utf-8", errors="replace"),
        }


def _headers(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("headers must be an object")
    headers: dict[str, str] = {}
    for key, item in value.items():
        name = str(key).strip()
        if not name:
            raise ValueError("header names must be non-empty")
        if name.casefold() in _SECRET_HEADER_NAMES:
            raise ValueError(f"header is not allowed in tool arguments: {name}")
        headers[name] = str(item)
    return headers


def _timeout(value: Any) -> float:
    if value is None:
        return 10.0
    return max(0.1, min(float(value), 30.0))


def _ensure_http_url(url: str) -> None:
    scheme = urlsplit(url).scheme.casefold()
    if scheme not in {"http", "https"}:
        raise ValueError(f"notification.webhook only supports http and https URLs: {url}")


def _allowed_domains(allowed_domains: list[str] | None) -> tuple[str, ...]:
    return tuple(
        domain.strip().casefold().lstrip(".")
        for domain in allowed_domains or []
        if domain.strip()
    )


def _ensure_allowed_domain(url: str, allowed_domains: tuple[str, ...]) -> None:
    if not allowed_domains:
        raise ValueError("notification.webhook has no allowed domains configured")
    host = (urlsplit(url).hostname or "").casefold()
    if any(host == domain or host.endswith(f".{domain}") for domain in allowed_domains):
        return
    raise ValueError(f"notification.webhook host is not in allowed domains: {host}")


def _url_without_query(url: str) -> str:
    parts = urlsplit(url)
    return parts._replace(query="", fragment="").geturl()
