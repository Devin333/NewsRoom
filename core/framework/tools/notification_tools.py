from __future__ import annotations

import json
from datetime import UTC, datetime
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from core.framework.tools.models import ToolDefinition
from core.framework.tools.registry import ToolRegistry


WebhookSender = Callable[[str, bytes, dict[str, str], float], dict[str, Any]]
_SECRET_HEADER_NAMES = {"authorization", "cookie", "x-api-key", "api-key"}


def register_notification_tools(
    registry: ToolRegistry,
    *,
    allowed_webhook_domains: list[str] | None = None,
    webhook_sender: WebhookSender | None = None,
    rss_feed_path: str | Path | None = None,
    rss_feed_title: str = "NewsRoom Updates",
    rss_feed_link: str = "https://localhost/",
    rss_feed_description: str = "NewsRoom published updates",
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
    if rss_feed_path is not None:
        rss_publisher = RssFeedPublisher(
            rss_feed_path,
            feed_title=rss_feed_title,
            feed_link=rss_feed_link,
            feed_description=rss_feed_description,
        )
        registry.register(
            ToolDefinition(
                name="notification.rss_publish",
                description="Publish an item to the configured RSS feed file.",
                input_schema={
                    "required": ["title", "link"],
                    "properties": {
                        "title": {"type": "string"},
                        "link": {"type": "string"},
                        "description": {"type": "string"},
                        "guid": {"type": "string"},
                        "published_at": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                side_effect="publishing",
                requires_approval=True,
                concurrency_safe=False,
                max_result_bytes=100_000,
                metadata={"notification_channel": "rss"},
            ),
            lambda args: _publish_rss(args, rss_publisher=rss_publisher),
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


class RssFeedPublisher:
    def __init__(
        self,
        path: str | Path,
        *,
        feed_title: str,
        feed_link: str,
        feed_description: str,
    ) -> None:
        self.path = Path(path)
        self.feed_title = feed_title
        self.feed_link = feed_link
        self.feed_description = feed_description

    def publish(
        self,
        *,
        title: str,
        link: str,
        description: str | None,
        guid: str | None,
        published_at: datetime,
    ) -> dict[str, Any]:
        root = self._load_or_create()
        channel = root.find("channel")
        if channel is None:
            raise ValueError("RSS feed is missing channel")
        item = ElementTree.SubElement(channel, "item")
        ElementTree.SubElement(item, "title").text = title
        ElementTree.SubElement(item, "link").text = link
        if description:
            ElementTree.SubElement(item, "description").text = description
        ElementTree.SubElement(item, "guid").text = guid or link
        ElementTree.SubElement(item, "pubDate").text = format_datetime(published_at, usegmt=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        ElementTree.ElementTree(root).write(
            self.path,
            encoding="utf-8",
            xml_declaration=True,
        )
        return {"item_count": len(channel.findall("item"))}

    def _load_or_create(self) -> ElementTree.Element:
        if self.path.exists():
            return ElementTree.parse(self.path).getroot()
        root = ElementTree.Element("rss", {"version": "2.0"})
        channel = ElementTree.SubElement(root, "channel")
        ElementTree.SubElement(channel, "title").text = self.feed_title
        ElementTree.SubElement(channel, "link").text = self.feed_link
        ElementTree.SubElement(channel, "description").text = self.feed_description
        return root


def _publish_rss(
    args: dict[str, Any],
    *,
    rss_publisher: RssFeedPublisher,
) -> dict[str, Any]:
    title = str(args["title"]).strip()
    if not title:
        raise ValueError("title is required")
    link = str(args["link"]).strip()
    if not link:
        raise ValueError("link is required")
    _ensure_http_url(link)
    published = rss_publisher.publish(
        title=title,
        link=link,
        description=_optional_text(args.get("description")),
        guid=_optional_text(args.get("guid")),
        published_at=_published_at(args.get("published_at")),
    )
    return {
        "published": True,
        "feed_path": str(rss_publisher.path),
        "item_count": published["item_count"],
        "title": title,
        "link": link,
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


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _published_at(value: Any) -> datetime:
    if value is None:
        return datetime.now(UTC)
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        parsed = parsedate_to_datetime(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


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
