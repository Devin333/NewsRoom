from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from html import unescape
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request

from domain.sources import RawSourceItem, SourceDefinition, SourceError
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
HACKERNEWS_API_URL = "https://hacker-news.firebaseio.com/v0"
HACKERNEWS_WEB_URL = "https://news.ycombinator.com"
HACKERNEWS_CONTENT_TYPES = ("application/json", "text/plain")
HACKERNEWS_STORY_LISTS = {
    "topstories",
    "newstories",
    "beststories",
    "askstories",
    "showstories",
    "jobstories",
}


class HackerNewsConnector:
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

    def fetch(
        self,
        source: SourceDefinition,
        *,
        story_list: str | None = None,
        limit: int | None = None,
    ) -> tuple[list[RawSourceItem], list[SourceError]]:
        policy = effective_fetch_policy(self.fetch_policy, source)
        self._last_response_metadata = None
        try:
            actual_story_list = _story_list_from_source(source, story_list=story_list)
            story_url = build_hackernews_story_list_url(source.url or HACKERNEWS_API_URL, actual_story_list)
            rate_limit = self._rate_limiter.reserve(
                story_url,
                limit_per_minute=self.fetch_policy.rate_limit_per_domain_per_minute,
            )
            if not rate_limit.allowed:
                return [], [rate_limited_source_error(source, rate_limit, url=story_url)]
            story_payload = run_with_fetch_retries(
                lambda: self._fetch_source_text(story_url, policy),
                policy,
            )
        except Exception as exc:
            error = _exception_source_error(source, exc, phase="fetch")
            return [], [attach_response_metadata_to_error(error, self._last_response_metadata)]
        story_response_metadata = self._last_response_metadata

        if not story_payload.strip():
            return [], [
                attach_response_metadata_to_error(
                    _source_error(
                        source,
                        "empty_source_response",
                        "Hacker News API returned an empty story list response",
                        metadata={"phase": "fetch", "retryable": True, "source_health_affecting": True},
                    ),
                    story_response_metadata,
                )
            ]

        try:
            story_ids = parse_hackernews_story_ids(story_payload, limit=_candidate_limit(limit))
        except Exception as exc:
            error = _exception_source_error(source, exc, phase="parse")
            return [], [attach_response_metadata_to_error(error, story_response_metadata)]

        if not story_ids:
            return [], [
                attach_response_metadata_to_error(
                    _source_error(
                        source,
                        "empty_hackernews_story_ids",
                        "Hacker News story list contained no story ids",
                        metadata={"phase": "parse", "retryable": False, "source_health_affecting": False},
                    ),
                    story_response_metadata,
                )
            ]

        items: list[RawSourceItem] = []
        for item_id in story_ids:
            if limit is not None and len(items) >= limit:
                break
            item_url = build_hackernews_item_url(source.url or HACKERNEWS_API_URL, item_id)
            try:
                item_payload = run_with_fetch_retries(
                    lambda: self._fetch_source_text(item_url, policy),
                    policy,
                )
            except Exception as exc:
                error = _exception_source_error(source, exc, phase="fetch")
                return [], [attach_response_metadata_to_error(error, self._last_response_metadata)]
            item_response_metadata = self._last_response_metadata
            try:
                item = self.parse_item(
                    source,
                    item_payload,
                    item_id=item_id,
                    story_list=actual_story_list,
                )
            except Exception as exc:
                error = _exception_source_error(source, exc, phase="parse")
                return [], [attach_response_metadata_to_error(error, item_response_metadata)]
            if item is not None:
                items.extend(attach_response_metadata_to_items([item], item_response_metadata))

        if not items:
            return [], [
                attach_response_metadata_to_error(
                    _source_error(
                        source,
                        "empty_hackernews_items",
                        "Hacker News story ids produced no valid items",
                        metadata={"phase": "parse", "retryable": False, "source_health_affecting": False},
                    ),
                    story_response_metadata,
                )
            ]
        return items, []

    def parse_item(
        self,
        source: SourceDefinition,
        content: str,
        *,
        item_id: int | None = None,
        story_list: str | None = None,
    ) -> RawSourceItem | None:
        payload = json.loads(content)
        if payload is None:
            return None
        if not isinstance(payload, dict):
            raise ValueError("Hacker News item response must be a JSON object")
        if payload.get("deleted") or payload.get("dead"):
            return None
        title = _optional_text(payload.get("title"))
        actual_item_id = _optional_int(payload.get("id")) or item_id
        if not title or actual_item_id is None:
            return None
        discussion_url = f"{HACKERNEWS_WEB_URL}/item?id={actual_item_id}"
        external_url = _optional_text(payload.get("url"))
        summary = _plain_text(_optional_text(payload.get("text")))
        item_hash = sha256(f"{source.source_id}|{actual_item_id}".encode("utf-8")).hexdigest()
        hn_type = _optional_text(payload.get("type"))
        return RawSourceItem(
            source_item_id=f"raw_{item_hash[:16]}",
            source_id=source.source_id,
            source_name=source.name,
            source_type=source.source_type,
            title=title,
            url=external_url or discussion_url,
            fetched_at=datetime.now(UTC),
            published_at=_unix_datetime(payload.get("time")),
            summary=summary,
            raw_content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            authors=[str(payload["by"])] if payload.get("by") else [],
            tags=[tag for tag in [story_list, hn_type] if tag],
            language=source.language,
            metadata=source_item_metadata(
                source,
                extra={
                    "hackernews_item_id": actual_item_id,
                    "hackernews_type": hn_type,
                    "story_list": story_list,
                    "score": _optional_int(payload.get("score")),
                    "comments_count": _optional_int(payload.get("descendants")),
                    "discussion_url": discussion_url,
                    "external_url": external_url,
                },
            ),
        )

    def _default_fetch_text(self, url: str, policy: SourceFetchPolicy | None = None) -> str:
        policy = policy or self.fetch_policy
        request = Request(url, headers={"User-Agent": policy.user_agent})
        with open_request_with_fetch_policy(request, policy) as response:
            self._last_response_metadata = response_metadata_from_http_response(response, url=url)
            ensure_supported_content_type(self._last_response_metadata.content_type, HACKERNEWS_CONTENT_TYPES)
            body = response.read(policy.max_bytes + 1)
        if len(body) > policy.max_bytes:
            raise ValueError(f"source response exceeds max_bytes: {policy.max_bytes}")
        return body.decode("utf-8", errors="replace")

    def _fetch_source_text(self, url: str, policy: SourceFetchPolicy) -> str:
        if self._uses_default_fetch:
            ensure_robots_allowed(url, policy)
            return self._default_fetch_text(url, policy)
        return self._fetch_text(url)


def build_hackernews_story_list_url(base_url: str, story_list: str) -> str:
    _ensure_story_list(story_list)
    return f"{base_url.rstrip('/')}/{story_list}.json"


def build_hackernews_item_url(base_url: str, item_id: int) -> str:
    return f"{base_url.rstrip('/')}/item/{int(item_id)}.json"


def parse_hackernews_story_ids(content: str, *, limit: int | None = None) -> list[int]:
    payload = json.loads(content)
    if not isinstance(payload, list):
        raise ValueError("Hacker News story list response must be a JSON array")
    story_ids = [int(item) for item in payload if isinstance(item, int) or str(item).isdigit()]
    return story_ids[:limit] if limit is not None else story_ids


def _story_list_from_source(source: SourceDefinition, *, story_list: str | None) -> str:
    if story_list and story_list.strip():
        return _ensure_story_list(story_list.strip())
    metadata_story_list = source.metadata.get("story_list")
    if isinstance(metadata_story_list, str) and metadata_story_list.strip():
        return _ensure_story_list(metadata_story_list.strip())
    return "topstories"


def _ensure_story_list(story_list: str) -> str:
    normalized = story_list.strip().casefold()
    if normalized not in HACKERNEWS_STORY_LISTS:
        raise ValueError(f"unsupported Hacker News story list: {story_list}")
    return normalized


def _candidate_limit(limit: int | None) -> int | None:
    if limit is None:
        return None
    return max(1, int(limit)) * 3


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
    classification = classify_source_exception(
        exc,
        phase=phase,
        invalid_config_keywords=("story list",),
    )
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
    return classify_source_exception(
        exc,
        phase=phase,
        invalid_config_keywords=("story list",),
    ).to_tuple()


def _is_timeout_exception(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, TimeoutError):
            return True
        return "timed out" in str(reason).casefold() or "timeout" in str(reason).casefold()
    return False


def _plain_text(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(re.sub(r"<[^>]+>", " ", unescape(value)).split()) or None


def _unix_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(int(value), tz=UTC)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)
