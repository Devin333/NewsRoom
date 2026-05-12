from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request

from domain.sources import RawSourceItem, SourceDefinition, SourceError
from sources.connectors.fetch_policy import (
    DomainRateLimiter,
    RobotsDisallowedError,
    SourceFetchPolicy,
    TooManyRedirectsError,
    UnsupportedContentTypeError,
    effective_fetch_policy,
    ensure_robots_allowed,
    ensure_supported_content_type,
    fetch_attempts,
    open_request_with_fetch_policy,
    rate_limited_source_error,
    run_with_fetch_retries,
)
from sources.connectors.metadata import source_item_metadata
from sources.processing.normalize import canonicalize_url

FetchText = Callable[[str], str]
HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")


EXTRACTOR_NAME = "stdlib_html_extractor"
SKIP_TEXT_TAGS = {"script", "style", "noscript", "svg"}
LOW_VALUE_TEXT_TAGS = {"nav", "header", "footer", "aside", "form"}
PUBLISHED_META_KEYS = {
    "article:published_time",
    "date",
    "dc.date",
    "dc.date.issued",
    "pubdate",
    "publishdate",
    "publish_date",
}
AUTHOR_META_KEYS = {"author", "article:author", "dc.creator"}


@dataclass(frozen=True)
class HtmlExtractionResult:
    title: str | None
    text: str | None
    summary: str | None
    published_at: datetime | None
    authors: list[str]
    canonical_url: str | None
    language: str | None
    confidence: float
    extractor_name: str = EXTRACTOR_NAME

    def to_dict(self) -> dict[str, object]:
        return {
            "title": self.title,
            "text": self.text,
            "summary": self.summary,
            "published_at": _dt(self.published_at),
            "authors": list(self.authors),
            "canonical_url": self.canonical_url,
            "language": self.language,
            "confidence": self.confidence,
            "extractor_name": self.extractor_name,
        }


class HtmlConnector:
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

    def fetch(
        self,
        source: SourceDefinition,
        *,
        limit: int | None = None,
    ) -> tuple[list[RawSourceItem], list[SourceError]]:
        policy = effective_fetch_policy(self.fetch_policy, source)
        rate_limit = self._rate_limiter.reserve(
            source.url,
            limit_per_minute=self.fetch_policy.rate_limit_per_domain_per_minute,
        )
        if not rate_limit.allowed:
            return [], [rate_limited_source_error(source, rate_limit, url=source.url)]

        try:
            html_text = run_with_fetch_retries(
                lambda: self._fetch_source_text(source.url, policy),
                policy,
            )
        except Exception as exc:
            return [], [_exception_source_error(source, exc, phase="fetch")]

        if not html_text.strip():
            return [], [
                _source_error(
                    source,
                    "empty_source_response",
                    "HTML source returned an empty response",
                    metadata={"phase": "fetch", "retryable": True, "source_health_affecting": True},
                )
            ]

        try:
            items = self.parse(source, html_text, limit=limit)
        except Exception as exc:
            return [], [_exception_source_error(source, exc, phase="parse")]

        if not items:
            return [], [
                _source_error(
                    source,
                    "empty_html_extraction",
                    "HTML source did not contain extractable text",
                    metadata={"phase": "parse", "retryable": False, "source_health_affecting": False},
                )
            ]
        return items, []

    def parse(
        self,
        source: SourceDefinition,
        html_text: str,
        *,
        limit: int | None = None,
    ) -> list[RawSourceItem]:
        extraction = extract_html(html_text)
        if not extraction.text and not extraction.title:
            return []
        fetched_at = datetime.now(UTC)
        url = canonicalize_url(extraction.canonical_url or source.url, base_url=source.url)
        title = extraction.title or source.name
        item_hash = sha256(f"{source.source_id}|{url}".encode("utf-8")).hexdigest()
        item = RawSourceItem(
            source_item_id=f"raw_{item_hash[:16]}",
            source_id=source.source_id,
            source_name=source.name,
            source_type=source.source_type,
            title=title,
            url=url,
            fetched_at=fetched_at,
            published_at=extraction.published_at,
            summary=extraction.summary,
            raw_content=extraction.text,
            authors=extraction.authors,
            language=extraction.language or source.language,
            metadata=source_item_metadata(
                source,
                extra={
                    "extractor_name": extraction.extractor_name,
                    "extraction_confidence": extraction.confidence,
                    "canonical_url": url,
                    "raw_html_bytes": len(html_text.encode("utf-8")),
                },
            ),
        )
        items = [item]
        return items[:limit] if limit else items

    def _default_fetch_text(self, url: str) -> str:
        request = Request(url, headers={"User-Agent": self.fetch_policy.user_agent})
        with open_request_with_fetch_policy(request, self.fetch_policy) as response:
            headers = getattr(response, "headers", None)
            content_type = headers.get_content_type() if headers is not None else None
            ensure_supported_content_type(content_type, HTML_CONTENT_TYPES)
            body = response.read(self.fetch_policy.max_bytes + 1)
        if len(body) > self.fetch_policy.max_bytes:
            raise ValueError(f"source response exceeds max_bytes: {self.fetch_policy.max_bytes}")
        return body.decode("utf-8", errors="replace")

    def _fetch_source_text(self, url: str, policy: SourceFetchPolicy) -> str:
        if self._uses_default_fetch:
            ensure_robots_allowed(url, policy)
        return self._fetch_text(url)


def extract_html(html_text: str) -> HtmlExtractionResult:
    parser = _SourceHtmlParser()
    parser.feed(html_text)
    parser.close()
    title = _first_text(parser.meta.get("og:title"), parser.title_text, parser.h1_text)
    text = _normalize_text(" ".join(parser.body_text))
    summary = _first_text(parser.meta.get("description"), parser.meta.get("og:description"))
    if summary is None and text:
        summary = _truncate(text, 240)
    canonical_url = _first_text(parser.canonical_url, parser.meta.get("og:url"))
    published_at = _parse_datetime(
        _first_text(*[parser.meta.get(key) for key in PUBLISHED_META_KEYS], parser.time_datetime)
    )
    authors = _authors(parser.meta)
    confidence = _confidence(
        title=title,
        text=text,
        summary=summary,
        published_at=published_at,
        authors=authors,
        canonical_url=canonical_url,
    )
    return HtmlExtractionResult(
        title=title,
        text=text or None,
        summary=summary,
        published_at=published_at,
        authors=authors,
        canonical_url=canonical_url,
        language=parser.language,
        confidence=confidence,
    )


class _SourceHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.body_text: list[str] = []
        self.title_parts: list[str] = []
        self.h1_parts: list[str] = []
        self.title_text: str | None = None
        self.h1_text: str | None = None
        self.canonical_url: str | None = None
        self.time_datetime: str | None = None
        self.language: str | None = None
        self._tag_stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        attr_map = {key.casefold(): value for key, value in attrs if value is not None}
        self._tag_stack.append(tag)
        if tag == "html" and attr_map.get("lang"):
            self.language = attr_map["lang"].strip() or None
        elif tag == "meta":
            key = _first_text(attr_map.get("property"), attr_map.get("name"))
            content = attr_map.get("content")
            if key and content:
                self.meta[key.strip().casefold()] = _normalize_text(content)
        elif tag == "link" and attr_map.get("href"):
            rel_tokens = {token.casefold() for token in (attr_map.get("rel") or "").split()}
            if "canonical" in rel_tokens:
                self.canonical_url = attr_map["href"].strip()
        elif tag == "time" and attr_map.get("datetime") and self.time_datetime is None:
            self.time_datetime = attr_map["datetime"].strip()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag == "title":
            self.title_text = _normalize_text(" ".join(self.title_parts)) or None
        elif tag == "h1" and self.h1_text is None:
            self.h1_text = _normalize_text(" ".join(self.h1_parts)) or None
        while self._tag_stack:
            popped = self._tag_stack.pop()
            if popped == tag:
                break

    def handle_data(self, data: str) -> None:
        text = _normalize_text(unescape(data))
        if not text:
            return
        if "title" in self._tag_stack:
            self.title_parts.append(text)
            return
        if "h1" in self._tag_stack:
            self.h1_parts.append(text)
        if self._should_collect_body_text():
            self.body_text.append(text)

    def _should_collect_body_text(self) -> bool:
        if "body" not in self._tag_stack:
            return False
        if any(tag in SKIP_TEXT_TAGS or tag in LOW_VALUE_TEXT_TAGS for tag in self._tag_stack):
            return False
        return True


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
    if isinstance(exc, RobotsDisallowedError):
        return "robots_disallowed", False
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


def _authors(meta: dict[str, str]) -> list[str]:
    authors: list[str] = []
    for key in AUTHOR_META_KEYS:
        value = meta.get(key)
        if value:
            authors.extend(part.strip() for part in re.split(r",|;", value) if part.strip())
    return list(dict.fromkeys(authors))


def _confidence(
    *,
    title: str | None,
    text: str | None,
    summary: str | None,
    published_at: datetime | None,
    authors: list[str],
    canonical_url: str | None,
) -> float:
    score = 0.0
    if title:
        score += 0.2
    if text:
        score += 0.35 if len(text) >= 80 else 0.15
    if summary:
        score += 0.15
    if published_at:
        score += 0.1
    if authors:
        score += 0.1
    if canonical_url:
        score += 0.1
    return round(min(1.0, score), 4)


def _first_text(*values: str | None) -> str | None:
    for value in values:
        if value and value.strip():
            return _normalize_text(value)
    return None


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 1].rstrip() + "..."


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


def _dt(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None
