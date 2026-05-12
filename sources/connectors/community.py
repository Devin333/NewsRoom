from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request

from domain.sources import RawSourceItem, SourceDefinition, SourceError
from sources.connectors.diagnostics import (
    SourceFetchResponseMetadata,
    attach_response_metadata_to_error,
    attach_response_metadata_to_items,
    response_metadata_from_http_response,
)
from sources.connectors.feed import FeedConnector
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
from sources.errors import classify_source_exception


FetchText = Callable[[str], str]
LOBSTERS_BASE_URL = "https://lobste.rs"
STACKOVERFLOW_API_URL = "https://api.stackexchange.com/2.3"
DEVTO_API_URL = "https://dev.to/api"
MEDIUM_BASE_URL = "https://medium.com"
JSON_CONTENT_TYPES = ("application/json", "text/json")


class _JsonCommunityConnector:
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

    def _fetch_json_items(
        self,
        source: SourceDefinition,
        *,
        url: str,
        parser,
        limit: int | None,
        empty_error_type: str,
        empty_error_message: str,
    ) -> tuple[list[RawSourceItem], list[SourceError]]:
        policy = effective_fetch_policy(self.fetch_policy, source)
        self._last_response_metadata = None
        try:
            rate_limit = self._rate_limiter.reserve(
                url,
                limit_per_minute=self.fetch_policy.rate_limit_per_domain_per_minute,
            )
            if not rate_limit.allowed:
                return [], [rate_limited_source_error(source, rate_limit, url=url)]
            payload = run_with_fetch_retries(lambda: self._fetch_source_text(url, policy), policy)
        except Exception as exc:
            error = _exception_source_error(source, exc, phase="fetch")
            return [], [attach_response_metadata_to_error(error, self._last_response_metadata)]
        response_metadata = self._last_response_metadata
        if not payload.strip():
            return [], [
                attach_response_metadata_to_error(
                    _source_error(
                        source,
                        "empty_source_response",
                        "community API returned an empty response",
                        metadata={"phase": "fetch", "retryable": True, "source_health_affecting": True},
                    ),
                    response_metadata,
                )
            ]
        try:
            items = parser(source, payload, limit=limit)
        except Exception as exc:
            error = _exception_source_error(source, exc, phase="parse")
            return [], [attach_response_metadata_to_error(error, response_metadata)]
        items = attach_response_metadata_to_items(items, response_metadata)
        if not items:
            return [], [
                attach_response_metadata_to_error(
                    _source_error(
                        source,
                        empty_error_type,
                        empty_error_message,
                        metadata={"phase": "parse", "retryable": False, "source_health_affecting": False},
                    ),
                    response_metadata,
                )
            ]
        return items, []

    def _default_fetch_text(self, url: str) -> str:
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": self.fetch_policy.user_agent,
            },
        )
        with open_request_with_fetch_policy(request, self.fetch_policy) as response:
            self._last_response_metadata = response_metadata_from_http_response(response, url=url)
            ensure_supported_content_type(self._last_response_metadata.content_type, JSON_CONTENT_TYPES)
            body = response.read(self.fetch_policy.max_bytes + 1)
        if len(body) > self.fetch_policy.max_bytes:
            raise ValueError(f"source response exceeds max_bytes: {self.fetch_policy.max_bytes}")
        return body.decode("utf-8", errors="replace")

    def _fetch_source_text(self, url: str, policy: SourceFetchPolicy) -> str:
        if self._uses_default_fetch:
            ensure_robots_allowed(url, policy)
        return self._fetch_text(url)


class LobstersConnector(_JsonCommunityConnector):
    def fetch(
        self,
        source: SourceDefinition,
        *,
        tag: str | None = None,
        limit: int | None = None,
    ) -> tuple[list[RawSourceItem], list[SourceError]]:
        return self._fetch_json_items(
            source,
            url=build_lobsters_url(source.url or LOBSTERS_BASE_URL, tag=tag or _metadata_text(source, "tag")),
            parser=parse_lobsters_items,
            limit=limit,
            empty_error_type="empty_lobsters_items",
            empty_error_message="Lobsters returned no stories",
        )


class StackOverflowConnector(_JsonCommunityConnector):
    def fetch(
        self,
        source: SourceDefinition,
        *,
        tag: str | None = None,
        site: str | None = None,
        limit: int | None = None,
    ) -> tuple[list[RawSourceItem], list[SourceError]]:
        tagged = tag or _metadata_text(source, "tagged") or _metadata_text(source, "tag")
        if not tagged:
            return [], [
                _source_error(
                    source,
                    "invalid_source_config",
                    "Stack Overflow source requires metadata.tagged or metadata.tag",
                    metadata={
                        "phase": "fetch",
                        "retryable": False,
                        "source_health_affecting": False,
                        "operator_action_required": True,
                    },
                )
            ]
        return self._fetch_json_items(
            source,
            url=build_stackoverflow_questions_url(
                source.url or STACKOVERFLOW_API_URL,
                tagged=tagged,
                site=site or _metadata_text(source, "site") or "stackoverflow",
                limit=limit or 10,
            ),
            parser=parse_stackoverflow_items,
            limit=limit,
            empty_error_type="empty_stackoverflow_questions",
            empty_error_message="Stack Overflow returned no questions",
        )


class DevToConnector(_JsonCommunityConnector):
    def fetch(
        self,
        source: SourceDefinition,
        *,
        tag: str | None = None,
        limit: int | None = None,
    ) -> tuple[list[RawSourceItem], list[SourceError]]:
        return self._fetch_json_items(
            source,
            url=build_devto_articles_url(
                source.url or DEVTO_API_URL,
                tag=tag or _metadata_text(source, "tag"),
                limit=limit or 10,
            ),
            parser=parse_devto_items,
            limit=limit,
            empty_error_type="empty_devto_articles",
            empty_error_message="dev.to returned no articles",
        )


class MediumConnector:
    def __init__(self, feed_connector: FeedConnector | None = None) -> None:
        self.feed_connector = feed_connector or FeedConnector()

    def fetch(
        self,
        source: SourceDefinition,
        *,
        tag: str | None = None,
        limit: int | None = None,
    ) -> tuple[list[RawSourceItem], list[SourceError]]:
        feed_url = build_medium_feed_url(source.url or MEDIUM_BASE_URL, tag=tag or _metadata_text(source, "tag"))
        feed_source = replace(source, url=feed_url)
        return self.feed_connector.fetch(feed_source, limit=limit)


def build_lobsters_url(base_url: str, *, tag: str | None = None) -> str:
    base = base_url.rstrip("/")
    if base.endswith(".json"):
        return base
    if tag:
        return f"{base}/t/{quote(tag.strip())}.json"
    return f"{base}/newest.json"


def build_stackoverflow_questions_url(
    base_url: str,
    *,
    tagged: str,
    site: str,
    limit: int,
) -> str:
    base = base_url.rstrip("/")
    params = urlencode(
        {
            "order": "desc",
            "sort": "activity",
            "tagged": tagged,
            "site": site,
            "pagesize": limit,
        }
    )
    return f"{base}/questions?{params}"


def build_devto_articles_url(base_url: str, *, tag: str | None = None, limit: int = 10) -> str:
    base = base_url.rstrip("/")
    params: dict[str, Any] = {"per_page": limit}
    if tag:
        params["tag"] = tag
    return f"{base}/articles?{urlencode(params)}"


def build_medium_feed_url(base_url: str, *, tag: str | None = None) -> str:
    base = base_url.rstrip("/")
    if "/feed/" in base:
        return base
    if tag:
        return f"{base}/feed/tag/{quote(tag.strip())}"
    return f"{base}/feed"


def parse_lobsters_items(
    source: SourceDefinition,
    content: str,
    *,
    limit: int | None = None,
) -> list[RawSourceItem]:
    payload = json.loads(content)
    if not isinstance(payload, list):
        raise ValueError("Lobsters response must be a JSON array")
    fetched_at = datetime.now(UTC)
    items = [
        _raw_lobsters_item(source, item, fetched_at=fetched_at)
        for item in payload
        if isinstance(item, dict)
    ]
    items = [item for item in items if item is not None]
    return items[:limit] if limit else items


def parse_stackoverflow_items(
    source: SourceDefinition,
    content: str,
    *,
    limit: int | None = None,
) -> list[RawSourceItem]:
    payload = json.loads(content)
    items_payload = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items_payload, list):
        raise ValueError("Stack Overflow response items must be a JSON array")
    fetched_at = datetime.now(UTC)
    items = [
        _raw_stackoverflow_item(source, item, fetched_at=fetched_at)
        for item in items_payload
        if isinstance(item, dict)
    ]
    items = [item for item in items if item is not None]
    return items[:limit] if limit else items


def parse_devto_items(
    source: SourceDefinition,
    content: str,
    *,
    limit: int | None = None,
) -> list[RawSourceItem]:
    payload = json.loads(content)
    if not isinstance(payload, list):
        raise ValueError("dev.to response must be a JSON array")
    fetched_at = datetime.now(UTC)
    items = [
        _raw_devto_item(source, item, fetched_at=fetched_at)
        for item in payload
        if isinstance(item, dict)
    ]
    items = [item for item in items if item is not None]
    return items[:limit] if limit else items


def _raw_lobsters_item(
    source: SourceDefinition,
    item: dict[str, Any],
    *,
    fetched_at: datetime,
) -> RawSourceItem | None:
    title = _optional_text(item.get("title"))
    url = _optional_text(item.get("url") or item.get("short_id_url") or item.get("comments_url"))
    if not title or not url:
        return None
    return _raw_item(
        source,
        title=title,
        url=url,
        fetched_at=fetched_at,
        published_at=_parse_datetime(item.get("created_at")),
        summary=_optional_text(item.get("description")),
        raw_payload=item,
        authors=[_optional_text(item.get("submitter_user"))],
        tags=["lobsters", *_string_list(item.get("tags"))],
        extra={
            "community_surface": "lobsters",
            "short_id": item.get("short_id"),
            "comments_url": item.get("comments_url"),
            "score": item.get("score"),
            "comment_count": item.get("comment_count"),
        },
    )


def _raw_stackoverflow_item(
    source: SourceDefinition,
    item: dict[str, Any],
    *,
    fetched_at: datetime,
) -> RawSourceItem | None:
    title = _optional_text(item.get("title"))
    url = _optional_text(item.get("link"))
    if not title or not url:
        return None
    owner = item.get("owner") if isinstance(item.get("owner"), dict) else {}
    return _raw_item(
        source,
        title=title,
        url=url,
        fetched_at=fetched_at,
        published_at=_parse_epoch(item.get("creation_date") or item.get("last_activity_date")),
        summary=None,
        raw_payload=item,
        authors=[_optional_text(owner.get("display_name"))],
        tags=["stackoverflow", *_string_list(item.get("tags"))],
        extra={
            "community_surface": "stackoverflow",
            "question_id": item.get("question_id"),
            "score": item.get("score"),
            "answer_count": item.get("answer_count"),
            "is_answered": item.get("is_answered"),
        },
    )


def _raw_devto_item(
    source: SourceDefinition,
    item: dict[str, Any],
    *,
    fetched_at: datetime,
) -> RawSourceItem | None:
    title = _optional_text(item.get("title"))
    url = _optional_text(item.get("url") or item.get("canonical_url"))
    if not title or not url:
        return None
    user = item.get("user") if isinstance(item.get("user"), dict) else {}
    return _raw_item(
        source,
        title=title,
        url=url,
        fetched_at=fetched_at,
        published_at=_parse_datetime(item.get("published_at") or item.get("created_at")),
        summary=_optional_text(item.get("description")),
        raw_payload=item,
        authors=[_optional_text(user.get("username") or user.get("name"))],
        tags=["devto", *_string_list(item.get("tag_list"))],
        extra={
            "community_surface": "devto",
            "article_id": item.get("id"),
            "positive_reactions_count": item.get("positive_reactions_count"),
            "comments_count": item.get("comments_count"),
        },
    )


def _raw_item(
    source: SourceDefinition,
    *,
    title: str,
    url: str,
    fetched_at: datetime,
    published_at: datetime | None,
    summary: str | None,
    raw_payload: dict[str, Any],
    authors: list[str | None],
    tags: list[str],
    extra: dict[str, Any],
) -> RawSourceItem:
    item_hash = sha256(f"{source.source_id}|{url}".encode("utf-8")).hexdigest()
    return RawSourceItem(
        source_item_id=f"raw_{item_hash[:16]}",
        source_id=source.source_id,
        source_name=source.name,
        source_type=source.source_type,
        title=title,
        url=url,
        fetched_at=fetched_at,
        published_at=published_at,
        summary=summary,
        raw_content=json.dumps(raw_payload, ensure_ascii=False, sort_keys=True),
        authors=[author for author in authors if author],
        tags=[tag for tag in tags if tag],
        language=source.language,
        metadata=source_item_metadata(source, extra=extra),
    )


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
    metadata: dict[str, object] = {
        "phase": phase,
        "original_exception_type": type(exc).__name__,
        "retryable": classification.retryable,
        "source_health_affecting": classification.source_health_affecting,
    }
    if isinstance(exc, UnsupportedContentTypeError):
        metadata["content_type"] = exc.content_type
        metadata["supported_content_types"] = list(exc.supported_content_types)
    if isinstance(exc, TooManyRedirectsError):
        metadata["redirect_url"] = exc.url
        metadata["max_redirects"] = exc.max_redirects
    if isinstance(exc, RobotsDisallowedError):
        metadata["robots_url"] = exc.robots_url
        metadata["user_agent"] = exc.user_agent
    if isinstance(exc, HTTPError):
        metadata["status_code"] = exc.code
    attempts = fetch_attempts(exc)
    if attempts is not None:
        metadata["attempts"] = attempts
    return _source_error(
        source,
        classification.error_type,
        str(exc),
        metadata=metadata,
    )


def _metadata_text(source: SourceDefinition, key: str) -> str | None:
    return _optional_text(source.metadata.get(key))


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_epoch(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError, OSError):
        return None
