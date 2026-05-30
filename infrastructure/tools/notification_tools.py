from __future__ import annotations

import json
import smtplib
import ssl
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from email.message import EmailMessage
from email.utils import format_datetime, getaddresses, make_msgid, parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from framework.tool.models import ToolDefinition
from framework.tool.registry import ToolRegistry


WebhookSender = Callable[[str, bytes, dict[str, str], float], dict[str, Any]]
EmailSender = Callable[[EmailMessage, list[str], float], dict[str, Any]]
_SECRET_HEADER_NAMES = {"authorization", "cookie", "x-api-key", "api-key"}


def register_notification_tools(
    registry: ToolRegistry,
    *,
    allowed_webhook_domains: list[str] | None = None,
    webhook_sender: WebhookSender | None = None,
    allowed_slack_domains: list[str] | None = None,
    slack_webhook_url: str | None = None,
    slack_sender: WebhookSender | None = None,
    allowed_email_domains: list[str] | None = None,
    email_sender: EmailSender | None = None,
    email_from_address: str | None = None,
    smtp_host: str | None = None,
    smtp_port: int = 587,
    smtp_username: str | None = None,
    smtp_password: str | None = None,
    smtp_use_tls: bool = False,
    smtp_use_starttls: bool = True,
    rss_feed_path: str | Path | None = None,
    rss_feed_title: str = "Framework Updates",
    rss_feed_link: str = "https://localhost/",
    rss_feed_description: str = "Framework published updates",
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
    if slack_webhook_url is not None:
        slack_url = str(slack_webhook_url).strip()
        slack_domain_tuple = _allowed_domains(allowed_slack_domains or ["hooks.slack.com"])
        slack_sender_fn = slack_sender or webhook_sender or _default_webhook_sender
        registry.register(
            ToolDefinition(
                name="notification.slack",
                description="Send a Slack incoming webhook notification through the configured URL.",
                input_schema={
                    "required": [],
                    "properties": {
                        "text": {"type": "string"},
                        "blocks": {"type": "array"},
                        "attachments": {"type": "array"},
                        "timeout_seconds": {"type": "number"},
                    },
                    "additionalProperties": False,
                },
                side_effect="writes_external_state",
                requires_approval=True,
                concurrency_safe=False,
                max_result_bytes=100_000,
                metadata={"notification_channel": "slack"},
            ),
            lambda args: _send_slack(
                args,
                webhook_url=slack_url,
                allowed_domains=slack_domain_tuple,
                sender=slack_sender_fn,
            ),
        )
    if email_sender is not None or smtp_host is not None or email_from_address is not None:
        from_address = _single_email_address(email_from_address, "email_from_address")
        sender_fn = email_sender or SmtpEmailSender(
            host=_required_text(smtp_host, "smtp_host"),
            port=smtp_port,
            username=smtp_username,
            password=smtp_password,
            use_tls=smtp_use_tls,
            use_starttls=smtp_use_starttls,
        )
        registry.register(
            ToolDefinition(
                name="notification.email",
                description="Send an email notification through the configured SMTP sender.",
                input_schema={
                    "required": ["to", "subject"],
                    "properties": {
                        "to": {"type": "array"},
                        "cc": {"type": "array"},
                        "bcc": {"type": "array"},
                        "subject": {"type": "string"},
                        "text_body": {"type": "string"},
                        "html_body": {"type": "string"},
                        "reply_to": {"type": "string"},
                        "timeout_seconds": {"type": "number"},
                    },
                    "additionalProperties": False,
                },
                side_effect="writes_external_state",
                requires_approval=True,
                concurrency_safe=False,
                max_result_bytes=100_000,
                metadata={"notification_channel": "email"},
            ),
            lambda args: _send_email(
                args,
                from_address=from_address,
                allowed_domains=_allowed_domains(allowed_email_domains),
                sender=sender_fn,
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


class SmtpEmailSender:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str | None = None,
        password: str | None = None,
        use_tls: bool = False,
        use_starttls: bool = True,
    ) -> None:
        self.host = _required_text(host, "smtp_host")
        self.port = int(port)
        if self.port <= 0:
            raise ValueError("smtp_port must be positive")
        if use_tls and use_starttls:
            raise ValueError("smtp_use_tls and smtp_use_starttls cannot both be true")
        if (username is None) != (password is None):
            raise ValueError("smtp_username and smtp_password must be configured together")
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.use_starttls = use_starttls

    def __call__(
        self,
        message: EmailMessage,
        recipients: list[str],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        context = ssl.create_default_context()
        smtp_cls = smtplib.SMTP_SSL if self.use_tls else smtplib.SMTP
        with smtp_cls(self.host, self.port, timeout=timeout_seconds) as smtp:
            if self.use_starttls:
                smtp.starttls(context=context)
            if self.username is not None and self.password is not None:
                smtp.login(self.username, self.password)
            refused = smtp.send_message(message, to_addrs=recipients)
        refused_recipients = sorted(str(recipient) for recipient in refused)
        accepted = [recipient for recipient in recipients if recipient not in refused]
        return {
            "accepted_recipients": accepted,
            "refused_recipients": refused_recipients,
        }


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


def _send_slack(
    args: dict[str, Any],
    *,
    webhook_url: str,
    allowed_domains: tuple[str, ...],
    sender: WebhookSender,
) -> dict[str, Any]:
    webhook_url = webhook_url.strip()
    if not webhook_url:
        raise ValueError("slack_webhook_url is required")
    _ensure_slack_url(webhook_url, allowed_domains)
    payload = _slack_payload(args)
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    response = sender(webhook_url, body, {}, _timeout(args.get("timeout_seconds")))
    parsed = urlsplit(webhook_url)
    return {
        "sent": True,
        "host": parsed.hostname,
        "status_code": response.get("status_code"),
        "content_type": response.get("content_type"),
        "response_preview": str(response.get("response_text") or "")[:500],
        "payload_bytes": len(body),
    }


def _send_email(
    args: dict[str, Any],
    *,
    from_address: str,
    allowed_domains: tuple[str, ...],
    sender: EmailSender,
) -> dict[str, Any]:
    to_addresses = _email_addresses(args["to"], "to")
    cc_addresses = _email_addresses(args.get("cc"), "cc")
    bcc_addresses = _email_addresses(args.get("bcc"), "bcc")
    recipients = to_addresses + cc_addresses + bcc_addresses
    if not recipients:
        raise ValueError("to must contain at least one recipient")
    _ensure_allowed_email_domains(recipients, allowed_domains)

    subject = _required_text(args["subject"], "subject")
    text_body = _optional_text(args.get("text_body"))
    html_body = _optional_text(args.get("html_body"))
    if text_body is None and html_body is None:
        raise ValueError("text_body or html_body is required")

    reply_to = args.get("reply_to")
    reply_to_address = (
        _single_email_address(reply_to, "reply_to") if reply_to is not None else None
    )
    if reply_to_address is not None:
        _ensure_allowed_email_domains([reply_to_address], allowed_domains)

    message = _email_message(
        from_address=from_address,
        to_addresses=to_addresses,
        cc_addresses=cc_addresses,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        reply_to=reply_to_address,
    )
    send_result = sender(message, recipients, _timeout(args.get("timeout_seconds")))
    accepted_recipients = list(send_result.get("accepted_recipients") or recipients)
    refused_recipients = list(send_result.get("refused_recipients") or [])
    return {
        "sent": True,
        "message_id": message["Message-ID"],
        "from": from_address,
        "to": list(to_addresses),
        "cc": list(cc_addresses),
        "bcc_count": len(bcc_addresses),
        "subject": subject,
        "accepted_count": len(accepted_recipients),
        "refused_count": len(refused_recipients),
        "refused_recipients": refused_recipients,
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
            "User-Agent": "FrameworkToolRuntime/1.0",
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


def _slack_payload(args: dict[str, Any]) -> dict[str, Any]:
    text = _optional_text(args.get("text"))
    blocks = _optional_object_array(args.get("blocks"), "blocks")
    attachments = _optional_object_array(args.get("attachments"), "attachments")
    if text is None and not blocks and not attachments:
        raise ValueError("text, blocks, or attachments is required")
    payload: dict[str, Any] = {}
    if text is not None:
        payload["text"] = text
    if blocks:
        payload["blocks"] = blocks
    if attachments:
        payload["attachments"] = attachments
    return payload


def _email_message(
    *,
    from_address: str,
    to_addresses: list[str],
    cc_addresses: list[str],
    subject: str,
    text_body: str | None,
    html_body: str | None,
    reply_to: str | None,
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = from_address
    message["To"] = ", ".join(to_addresses)
    if cc_addresses:
        message["Cc"] = ", ".join(cc_addresses)
    if reply_to is not None:
        message["Reply-To"] = reply_to
    message["Subject"] = subject
    message["Date"] = format_datetime(datetime.now(UTC), usegmt=True)
    message["Message-ID"] = make_msgid(domain=_email_domain(from_address))
    if text_body is not None:
        message.set_content(text_body)
        if html_body is not None:
            message.add_alternative(html_body, subtype="html")
    else:
        message.set_content(html_body or "", subtype="html")
    return message


def _email_addresses(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an array")
    addresses: list[str] = []
    for _, address in getaddresses([str(item) for item in value]):
        normalized = address.strip().casefold()
        if not _is_email_address(normalized):
            raise ValueError(f"{field_name} contains an invalid email address")
        addresses.append(normalized)
    if len(addresses) != len(value):
        raise ValueError(f"{field_name} contains an invalid email address")
    return addresses


def _optional_object_array(value: Any, field_name: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an array")
    objects: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(f"{field_name} items must be objects")
        objects.append(dict(item))
    return objects


def _single_email_address(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name)
    addresses = _email_addresses([text], field_name)
    if len(addresses) != 1:
        raise ValueError(f"{field_name} must contain exactly one email address")
    return addresses[0]


def _is_email_address(value: str) -> bool:
    local_part, separator, domain = value.partition("@")
    return bool(local_part and separator and _email_domain(value))


def _email_domain(value: str) -> str:
    return value.rsplit("@", maxsplit=1)[-1].casefold()


def _ensure_allowed_email_domains(addresses: list[str], allowed_domains: tuple[str, ...]) -> None:
    if not allowed_domains:
        raise ValueError("notification.email has no allowed email domains configured")
    for address in addresses:
        domain = _email_domain(address)
        if any(domain == allowed or domain.endswith(f".{allowed}") for allowed in allowed_domains):
            continue
        raise ValueError(f"notification.email recipient domain is not allowed: {domain}")


def _timeout(value: Any) -> float:
    if value is None:
        return 10.0
    return max(0.1, min(float(value), 30.0))


def _required_text(value: Any, field_name: str) -> str:
    if value is None:
        raise ValueError(f"{field_name} is required")
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


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


def _ensure_slack_url(url: str, allowed_domains: tuple[str, ...]) -> None:
    parts = urlsplit(url)
    scheme = parts.scheme.casefold()
    host = (parts.hostname or "").casefold()
    if scheme == "https":
        pass
    elif scheme == "http" and host in {"127.0.0.1", "localhost"}:
        pass
    else:
        raise ValueError(f"notification.slack only supports https URLs: {url}")
    if any(host == domain or host.endswith(f".{domain}") for domain in allowed_domains):
        return
    raise ValueError(f"notification.slack host is not in allowed domains: {host}")


def _url_without_query(url: str) -> str:
    parts = urlsplit(url)
    return parts._replace(query="", fragment="").geturl()

