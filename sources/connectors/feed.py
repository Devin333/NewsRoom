from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from hashlib import sha256
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request
from xml.etree import ElementTree

from domain.sources import RawSourceItem, SourceDefinition, SourceError, SourceType
from sources.connectors.fetch_policy import (
    DomainRateLimiter,
    SourceFetchPolicy,
    TooManyRedirectsError,
    UnsupportedContentTypeError,
    ensure_supported_content_type,
    fetch_attempts,
    open_request_with_fetch_policy,
    rate_limited_source_error,
    run_with_fetch_retries,
)
from sources.connectors.metadata import source_item_metadata


FetchText = Callable[[str], str]
FEED_CONTENT_TYPES = (
    "application/rss+xml",
    "application/atom+xml",
    "application/xml",
    "application/rdf+xml",
    "text/xml",
)


class FeedConnector:
    def __init__(
        self,
        fetch_text: FetchText | None = None,
        *,
        fetch_policy: SourceFetchPolicy | None = None,
        rate_limiter: DomainRateLimiter | None = None,
    ) -> None:
        self.fetch_policy = fetch_policy or SourceFetchPolicy()
        self._rate_limiter = rate_limiter or DomainRateLimiter()
        self._fetch_text = fetch_text or self._default_fetch_text

    def fetch(self, source: SourceDefinition, *, limit: int | None = None) -> tuple[list[RawSourceItem], list[SourceError]]:
        rate_limit = self._rate_limiter.reserve(
            source.url,
            limit_per_minute=self.fetch_policy.rate_limit_per_domain_per_minute,
        )
        if not rate_limit.allowed:
            return [], [rate_limited_source_error(source, rate_limit, url=source.url)]

        try:
            xml_text = run_with_fetch_retries(
                lambda: self._fetch_text(source.url),
                self.fetch_policy,
            )
        except Exception as exc:
            return [], [_exception_source_error(source, exc, phase="fetch")]

        if not xml_text.strip():
            return [], [
                _source_error(
                    source,
                    "empty_source_response",
                    "source returned an empty response",
                    metadata={
                        "phase": "fetch",
                        "retryable": True,
                        "source_health_affecting": True,
                    },
                )
            ]

        try:
            items = self.parse(source, xml_text, limit=limit)
        except Exception as exc:
            return [], [_exception_source_error(source, exc, phase="parse")]

        if not items:
            return [], [
                _source_error(
                    source,
                    "empty_feed",
                    "feed contained no valid items",
                    metadata={
                        "phase": "parse",
                        "retryable": False,
                        "source_health_affecting": False,
                    },
                )
            ]
        return items, []

    def parse(self, source: SourceDefinition, xml_text: str, *, limit: int | None = None) -> list[RawSourceItem]:
        root = ElementTree.fromstring(xml_text)
        fetched_at = datetime.now(UTC)
        if _local_name(root.tag) == "rss":
            items = self._parse_rss(source, root, fetched_at)
        elif _local_name(root.tag) == "feed":
            items = self._parse_atom(source, root, fetched_at)
        else:
            raise ValueError(f"unsupported feed root: {_local_name(root.tag)}")
        return items[:limit] if limit else items

    def _parse_rss(
        self,
        source: SourceDefinition,
        root: ElementTree.Element,
        fetched_at: datetime,
    ) -> list[RawSourceItem]:
        channel = root.find("channel")
        if channel is None:
            raise ValueError("rss feed missing channel")
        raw_items = []
        for item in channel.findall("item"):
            title = _text(item, "title")
            url = _text(item, "link")
            if not title or not url:
                continue
            raw_items.append(
                _raw_item(
                    source=source,
                    title=title,
                    url=url,
                    fetched_at=fetched_at,
                    published_at=_parse_datetime(_text(item, "pubDate")),
                    summary=_text(item, "description"),
                    raw_content=ElementTree.tostring(item, encoding="unicode"),
                )
            )
        return raw_items

    def _parse_atom(
        self,
        source: SourceDefinition,
        root: ElementTree.Element,
        fetched_at: datetime,
    ) -> list[RawSourceItem]:
        raw_items = []
        for entry in _children(root, "entry"):
            title = _child_text(entry, "title")
            url = _atom_link(entry)
            if not title or not url:
                continue
            raw_items.append(
                _raw_item(
                    source=source,
                    title=title,
                    url=url,
                    fetched_at=fetched_at,
                    published_at=_parse_datetime(
                        _child_text(entry, "published") or _child_text(entry, "updated")
                    ),
                    summary=_child_text(entry, "summary") or _child_text(entry, "content"),
                    raw_content=ElementTree.tostring(entry, encoding="unicode"),
                )
            )
        return raw_items

    def _default_fetch_text(self, url: str) -> str:
        request = Request(url, headers={"User-Agent": self.fetch_policy.user_agent})
        with open_request_with_fetch_policy(request, self.fetch_policy) as response:
            headers = getattr(response, "headers", None)
            content_type = headers.get_content_type() if headers is not None else None
            ensure_supported_content_type(content_type, FEED_CONTENT_TYPES)
            body = response.read(self.fetch_policy.max_bytes + 1)
        if len(body) > self.fetch_policy.max_bytes:
            raise ValueError(f"source response exceeds max_bytes: {self.fetch_policy.max_bytes}")
        return body.decode("utf-8", errors="replace")


def _source_error(
    source: SourceDefinition,
    error_type: str,
    error_message: str,
    *,
    metadata: dict[str, object] | None = None,
) -> SourceError:
    return SourceError(
        source_id=source.source_id,
        error_type=error_type,
        error_message=error_message,
        url=source.url,
        metadata=metadata or {},
    )


def _exception_source_error(source: SourceDefinition, exc: Exception, *, phase: str) -> SourceError:
    error_type, retryable = _taxonomy_for_exception(exc, phase=phase)
    metadata: dict[str, object] = {
        "phase": phase,
        "original_exception_type": type(exc).__name__,
        "retryable": retryable,
        "source_health_affecting": phase == "fetch" or retryable,
    }
    if isinstance(exc, UnsupportedContentTypeError):
        metadata["content_type"] = exc.content_type
        metadata["supported_content_types"] = list(exc.supported_content_types)
        metadata["source_health_affecting"] = False
    if isinstance(exc, TooManyRedirectsError):
        metadata["redirect_url"] = exc.url
        metadata["max_redirects"] = exc.max_redirects
        metadata["source_health_affecting"] = False
    if isinstance(exc, HTTPError):
        metadata["status_code"] = exc.code
    attempts = fetch_attempts(exc)
    if attempts is not None:
        metadata["attempts"] = attempts
    return _source_error(source, error_type, str(exc), metadata=metadata)


def _taxonomy_for_exception(exc: Exception, *, phase: str) -> tuple[str, bool]:
    if phase == "parse":
        return "parse_error", False
    if isinstance(exc, HTTPError):
        if 400 <= exc.code < 500:
            return "fetch_http_4xx", exc.code in {408, 409, 425, 429}
        if exc.code >= 500:
            return "fetch_http_5xx", True
        return "fetch_connection_error", True
    if _is_timeout_exception(exc):
        return "fetch_timeout", True
    if isinstance(exc, UnsupportedContentTypeError):
        return "unsupported_content_type", False
    if isinstance(exc, TooManyRedirectsError):
        return "too_many_redirects", False
    if isinstance(exc, ValueError) and "max_bytes" in str(exc):
        return "max_bytes_exceeded", False
    return "fetch_connection_error", True


def _is_timeout_exception(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, TimeoutError):
            return True
        return "timed out" in str(reason).casefold() or "timeout" in str(reason).casefold()
    return False


def _raw_item(
    *,
    source: SourceDefinition,
    title: str,
    url: str,
    fetched_at: datetime,
    published_at: datetime | None,
    summary: str | None,
    raw_content: str,
) -> RawSourceItem:
    item_hash = sha256(f"{source.source_id}|{url}".encode("utf-8")).hexdigest()
    return RawSourceItem(
        source_item_id=f"raw_{item_hash[:16]}",
        source_id=source.source_id,
        source_name=source.name,
        source_type=source.source_type,
        title=title.strip(),
        url=url.strip(),
        fetched_at=fetched_at,
        published_at=published_at,
        summary=summary.strip() if summary else None,
        raw_content=raw_content,
        language=source.language,
        metadata=source_item_metadata(source),
    )


def _text(parent: ElementTree.Element, tag: str) -> str | None:
    child = parent.find(tag)
    return child.text.strip() if child is not None and child.text else None


def _children(parent: ElementTree.Element, local_name: str) -> list[ElementTree.Element]:
    return [child for child in list(parent) if _local_name(child.tag) == local_name]


def _child_text(parent: ElementTree.Element, local_name: str) -> str | None:
    for child in _children(parent, local_name):
        return child.text.strip() if child.text else None
    return None


def _atom_link(entry: ElementTree.Element) -> str | None:
    for child in _children(entry, "link"):
        href = child.attrib.get("href")
        if href and child.attrib.get("rel", "alternate") == "alternate":
            return href.strip()
    return None


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except (TypeError, ValueError):
        pass
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except ValueError:
        return None
