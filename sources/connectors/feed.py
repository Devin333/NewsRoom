from __future__ import annotations

import json
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html import unescape
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request
from xml.etree import ElementTree

from domain.sources import RawSourceItem, SourceDefinition, SourceError, SourceType
from sources.connectors.diagnostics import (
    SourceFetchResponseMetadata,
    attach_response_metadata_to_error,
    attach_response_metadata_to_items,
    response_metadata_from_http_response,
)
from sources.connectors.fetch_policy import (
    DomainRateLimiter,
    RobotsDisallowedError,
    SourceFetchPolicy,
    TooManyRedirectsError,
    UnsupportedContentTypeError,
    effective_fetch_policy,
    ensure_supported_content_type,
    ensure_robots_allowed,
    fetch_attempts,
    open_request_with_fetch_policy,
    rate_limited_source_error,
    run_with_fetch_retries,
)
from sources.connectors.metadata import source_item_metadata
from sources.errors import classify_source_exception


FetchText = Callable[[str], str]
FEED_CONTENT_TYPES = (
    "application/rss+xml",
    "application/atom+xml",
    "application/feed+json",
    "application/json",
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
        self._uses_default_fetch = fetch_text is None
        self._fetch_text = fetch_text or self._default_fetch_text
        self._last_response_metadata: SourceFetchResponseMetadata | None = None

    def fetch(self, source: SourceDefinition, *, limit: int | None = None) -> tuple[list[RawSourceItem], list[SourceError]]:
        policy = effective_fetch_policy(self.fetch_policy, source)
        self._last_response_metadata = None
        rate_limit = self._rate_limiter.reserve(
            source.url,
            limit_per_minute=self.fetch_policy.rate_limit_per_domain_per_minute,
        )
        if not rate_limit.allowed:
            return [], [rate_limited_source_error(source, rate_limit, url=source.url)]

        try:
            xml_text = run_with_fetch_retries(
                lambda: self._fetch_source_text(source.url, policy),
                policy,
            )
        except Exception as exc:
            error = _exception_source_error(source, exc, phase="fetch")
            return [], [attach_response_metadata_to_error(error, self._last_response_metadata)]
        response_metadata = self._last_response_metadata

        if not xml_text.strip():
            return [], [
                attach_response_metadata_to_error(
                    _source_error(
                        source,
                        "empty_source_response",
                        "source returned an empty response",
                        metadata={
                            "phase": "fetch",
                            "retryable": True,
                            "source_health_affecting": True,
                        },
                    ),
                    response_metadata,
                )
            ]

        try:
            items = self.parse(source, xml_text, limit=limit)
        except Exception as exc:
            error = _exception_source_error(source, exc, phase="parse")
            return [], [attach_response_metadata_to_error(error, response_metadata)]
        items = attach_response_metadata_to_items(items, response_metadata)

        if not items:
            return [], [
                attach_response_metadata_to_error(
                    _source_error(
                        source,
                        "empty_feed",
                        "feed contained no valid items",
                        metadata={
                            "phase": "parse",
                            "retryable": False,
                            "source_health_affecting": False,
                        },
                    ),
                    response_metadata,
                )
            ]
        return items, []

    def parse(self, source: SourceDefinition, xml_text: str, *, limit: int | None = None) -> list[RawSourceItem]:
        stripped = xml_text.strip()
        if stripped.startswith("{"):
            items = self._parse_json_feed(source, stripped, datetime.now(UTC))
            return items[:limit] if limit else items
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

    def _parse_json_feed(
        self,
        source: SourceDefinition,
        json_text: str,
        fetched_at: datetime,
    ) -> list[RawSourceItem]:
        payload = json.loads(json_text)
        if not isinstance(payload, dict):
            raise ValueError("json feed root must be an object")
        entries = payload.get("items")
        if not isinstance(entries, list):
            raise ValueError("json feed items must be an array")
        feed_language = _json_text(payload.get("language"))
        raw_items = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            item = _json_feed_item(
                source=source,
                feed=payload,
                entry=entry,
                fetched_at=fetched_at,
                feed_language=feed_language,
            )
            if item is not None:
                raw_items.append(item)
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

    def _default_fetch_text(self, url: str, policy: SourceFetchPolicy | None = None) -> str:
        policy = policy or self.fetch_policy
        request = Request(url, headers={"User-Agent": policy.user_agent})
        with open_request_with_fetch_policy(request, policy) as response:
            self._last_response_metadata = response_metadata_from_http_response(response, url=url)
            ensure_supported_content_type(self._last_response_metadata.content_type, FEED_CONTENT_TYPES)
            body = response.read(policy.max_bytes + 1)
        if len(body) > policy.max_bytes:
            raise ValueError(f"source response exceeds max_bytes: {policy.max_bytes}")
        return body.decode("utf-8", errors="replace")

    def _fetch_source_text(self, url: str, policy: SourceFetchPolicy) -> str:
        if self._uses_default_fetch:
            ensure_robots_allowed(url, policy)
            return self._default_fetch_text(url, policy)
        return self._fetch_text(url)


def _source_error(
    source: SourceDefinition,
    error_type: str,
    error_message: str,
    *,
    metadata: dict[str, object] | None = None,
) -> SourceError:
    return SourceError(
        source_id=source.source_id,
        source_name=source.name,
        error_type=error_type,
        error_message=error_message,
        url=source.url,
        metadata=metadata or {},
    )


def _exception_source_error(source: SourceDefinition, exc: Exception, *, phase: str) -> SourceError:
    classification = classify_source_exception(exc, phase=phase)
    error_type, retryable = classification.to_tuple()
    metadata: dict[str, object] = {
        "phase": phase,
        "original_exception_type": type(exc).__name__,
        "retryable": retryable,
        "source_health_affecting": classification.source_health_affecting,
    }
    if classification.operator_action_required:
        metadata["operator_action_required"] = True
    if isinstance(exc, UnsupportedContentTypeError):
        metadata["content_type"] = exc.content_type
        metadata["supported_content_types"] = list(exc.supported_content_types)
        metadata["source_health_affecting"] = False
    if isinstance(exc, TooManyRedirectsError):
        metadata["redirect_url"] = exc.url
        metadata["max_redirects"] = exc.max_redirects
        metadata["source_health_affecting"] = False
    if isinstance(exc, RobotsDisallowedError):
        metadata["robots_url"] = exc.robots_url
        metadata["user_agent"] = exc.user_agent
        metadata["source_health_affecting"] = False
    if isinstance(exc, HTTPError):
        metadata["status_code"] = exc.code
    attempts = fetch_attempts(exc)
    if attempts is not None:
        metadata["attempts"] = attempts
    return _source_error(source, error_type, str(exc), metadata=metadata)


def _taxonomy_for_exception(exc: Exception, *, phase: str) -> tuple[str, bool]:
    return classify_source_exception(exc, phase=phase).to_tuple()


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


def _json_feed_item(
    *,
    source: SourceDefinition,
    feed: dict[str, object],
    entry: dict[str, object],
    fetched_at: datetime,
    feed_language: str | None,
) -> RawSourceItem | None:
    url = _json_text(entry.get("url")) or _json_text(entry.get("external_url")) or _json_text(entry.get("id"))
    summary = (
        _json_text(entry.get("summary"))
        or _json_text(entry.get("content_text"))
        or _plain_text(_json_text(entry.get("content_html")))
    )
    title = _json_text(entry.get("title")) or _title_from_summary(summary)
    if not title or not url:
        return None
    item_id = _json_text(entry.get("id")) or url
    item_hash = sha256(f"{source.source_id}|{item_id}".encode("utf-8")).hexdigest()
    return RawSourceItem(
        source_item_id=f"raw_{item_hash[:16]}",
        source_id=source.source_id,
        source_name=source.name,
        source_type=source.source_type,
        title=title,
        url=url,
        fetched_at=fetched_at,
        published_at=_parse_datetime(
            _json_text(entry.get("date_published")) or _json_text(entry.get("date_modified"))
        ),
        summary=summary,
        raw_content=json.dumps(entry, ensure_ascii=False, sort_keys=True),
        authors=_json_feed_authors(entry),
        tags=_json_string_list(entry.get("tags")),
        language=_json_text(entry.get("language")) or source.language or feed_language,
        metadata=source_item_metadata(
            source,
            extra={
                "feed_format": "json_feed",
                "json_feed_version": _json_text(feed.get("version")),
                "json_feed_item_id": item_id,
                "feed_home_page_url": _json_text(feed.get("home_page_url")),
                "feed_url": _json_text(feed.get("feed_url")),
            },
        ),
    )


def _json_feed_authors(entry: dict[str, object]) -> list[str]:
    authors = []
    authors.extend(_json_author_names(entry.get("authors")))
    authors.extend(_json_author_names(entry.get("author")))
    return list(dict.fromkeys(authors))


def _json_author_names(value: object) -> list[str]:
    if isinstance(value, dict):
        name = _json_text(value.get("name")) or _json_text(value.get("url"))
        return [name] if name else []
    if isinstance(value, list):
        names = []
        for item in value:
            names.extend(_json_author_names(item))
        return names
    return []


def _json_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _json_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _title_from_summary(summary: str | None) -> str | None:
    if not summary:
        return None
    return summary[:117].rstrip() + "..." if len(summary) > 120 else summary


def _plain_text(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(unescape(value).split())


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
