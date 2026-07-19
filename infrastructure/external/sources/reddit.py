from __future__ import annotations

import json
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from hashlib import sha256
from typing import Any, Callable
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request

from infrastructure.external.sources.models import RawSourceItem, SourceDefinition, SourceError
from infrastructure.external.sources.diagnostics import (
    SourceFetchResponseMetadataContext,
    attach_response_metadata_to_error,
    attach_response_metadata_to_items,
    response_metadata_from_http_response,
    source_fetch_response_scope,
)
from infrastructure.external.sources.fetch_policy import (
    DomainRateLimiter,
    SourceFetchPolicy,
    effective_fetch_policy,
    ensure_robots_allowed,
    ensure_supported_content_type,
    open_request_with_fetch_policy,
    run_with_fetch_retries,
)
from infrastructure.external.sources.metadata import source_item_metadata
from infrastructure.external.sources.errors import (
    SourceErrorContext,
    SourceTaxonomyExtension,
    build_source_error,
    rate_limited_source_error,
    source_error_from_exception,
)


FetchText = Callable[[str], str]
REDDIT_BASE_URL = "https://www.reddit.com"
REDDIT_CONTENT_TYPES = ("application/json", "text/json")
REDDIT_LISTINGS = {"hot", "new", "top", "rising", "controversial"}
REDDIT_TIME_RANGES = {"hour", "day", "week", "month", "year", "all"}
REDDIT_TAXONOMY_EXTENSION = SourceTaxonomyExtension(
    invalid_config_keywords=("subreddit", "listing", "time range"),
)


class RedditConnector:
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
        self._response_metadata_context = SourceFetchResponseMetadataContext()

    @source_fetch_response_scope
    def fetch(
        self,
        source: SourceDefinition,
        *,
        subreddit: str | None = None,
        listing: str | None = None,
        time_range: str | None = None,
        limit: int | None = None,
    ) -> tuple[list[RawSourceItem], list[SourceError]]:
        policy = effective_fetch_policy(self.fetch_policy, source)
        try:
            actual_subreddit = _subreddit_from_source(source, subreddit=subreddit)
            actual_listing = _listing_from_source(source, listing=listing)
            actual_time_range = _time_range_from_source(source, time_range=time_range)
            listing_url = build_reddit_listing_url(
                source.url or REDDIT_BASE_URL,
                actual_subreddit,
                actual_listing,
                limit=limit or 10,
                time_range=actual_time_range,
            )
            rate_limit = self._rate_limiter.reserve(
                listing_url,
                limit_per_minute=self.fetch_policy.rate_limit_per_domain_per_minute,
            )
            if not rate_limit.allowed:
                return [], [rate_limited_source_error(source, rate_limit, url=listing_url)]
            payload = run_with_fetch_retries(
                lambda: self._fetch_source_text(listing_url, policy),
                policy,
            )
        except Exception as exc:
            error = source_error_from_exception(
                source,
                exc,
                context=SourceErrorContext(phase="fetch"),
                extension=REDDIT_TAXONOMY_EXTENSION,
            )
            return [], [attach_response_metadata_to_error(error, self._response_metadata_context.get())]
        response_metadata = self._response_metadata_context.get()

        if not payload.strip():
            return [], [
                attach_response_metadata_to_error(
                    build_source_error(
                        source,
                        "empty_source_response",
                        "Reddit API returned an empty listing response",
                        context=SourceErrorContext(phase="fetch"),
                        retryable=True,
                        source_health_affecting=True,
                    ),
                    response_metadata,
                )
            ]

        try:
            items = self.parse_listing(
                source,
                payload,
                subreddit=actual_subreddit,
                listing=actual_listing,
                limit=limit,
            )
        except Exception as exc:
            error = source_error_from_exception(
                source,
                exc,
                context=SourceErrorContext(phase="parse"),
                extension=REDDIT_TAXONOMY_EXTENSION,
            )
            return [], [attach_response_metadata_to_error(error, response_metadata)]
        items = attach_response_metadata_to_items(items, response_metadata)

        if not items:
            return [], [
                attach_response_metadata_to_error(
                    build_source_error(
                        source,
                        "empty_reddit_posts",
                        "Reddit listing contained no valid posts",
                        context=SourceErrorContext(phase="parse"),
                        retryable=False,
                        source_health_affecting=False,
                    ),
                    response_metadata,
                )
            ]
        return items, []

    def parse_listing(
        self,
        source: SourceDefinition,
        content: str,
        *,
        subreddit: str | None = None,
        listing: str | None = None,
        limit: int | None = None,
    ) -> list[RawSourceItem]:
        payload = json.loads(content)
        if not isinstance(payload, dict):
            raise ValueError("Reddit listing response must be a JSON object")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError("Reddit listing response data must be an object")
        children = data.get("children")
        if not isinstance(children, list):
            raise ValueError("Reddit listing response children must be an array")
        fetched_at = datetime.now(UTC)
        items = [
            _raw_item_from_child(
                source=source,
                child=child,
                fetched_at=fetched_at,
                subreddit=subreddit,
                listing=listing,
            )
            for child in children
            if isinstance(child, dict)
        ]
        items = [item for item in items if item is not None]
        return items[:limit] if limit else items

    def _default_fetch_text(self, url: str, policy: SourceFetchPolicy | None = None) -> str:
        policy = policy or self.fetch_policy
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": policy.user_agent,
            },
        )
        with open_request_with_fetch_policy(request, policy) as response:
            response_metadata = response_metadata_from_http_response(response, url=url)
            self._response_metadata_context.set(response_metadata)
            ensure_supported_content_type(response_metadata.content_type, REDDIT_CONTENT_TYPES)
            body = response.read(policy.max_bytes + 1)
        if len(body) > policy.max_bytes:
            raise ValueError(f"source response exceeds max_bytes: {policy.max_bytes}")
        return body.decode("utf-8", errors="replace")

    def _fetch_source_text(self, url: str, policy: SourceFetchPolicy) -> str:
        if self._uses_default_fetch:
            ensure_robots_allowed(url, policy)
            return self._default_fetch_text(url, policy)
        return self._fetch_text(url)


def build_reddit_listing_url(
    base_url: str,
    subreddit: str,
    listing: str,
    *,
    limit: int,
    time_range: str | None = None,
) -> str:
    subreddit = _ensure_subreddit(subreddit)
    listing = _ensure_listing(listing)
    origin = _origin(base_url)
    params: dict[str, Any] = {"limit": max(1, int(limit))}
    if listing in {"top", "controversial"} and time_range:
        params["t"] = _ensure_time_range(time_range)
    return f"{origin}/r/{quote(subreddit)}/{listing}.json?{urlencode(params)}"


def _raw_item_from_child(
    *,
    source: SourceDefinition,
    child: dict[str, Any],
    fetched_at: datetime,
    subreddit: str | None,
    listing: str | None,
) -> RawSourceItem | None:
    post = child.get("data")
    if not isinstance(post, dict):
        return None
    title = _optional_text(post.get("title"))
    reddit_id = _optional_text(post.get("id"))
    permalink = _reddit_url(_optional_text(post.get("permalink")))
    if not title or not reddit_id or not permalink:
        return None
    external_url = _optional_text(post.get("url_overridden_by_dest")) or _optional_text(post.get("url"))
    url = external_url or permalink
    summary = _optional_text(post.get("selftext"))
    flair = _optional_text(post.get("link_flair_text"))
    item_hash = sha256(f"{source.source_id}|{reddit_id}".encode("utf-8")).hexdigest()
    post_subreddit = _optional_text(post.get("subreddit")) or subreddit
    return RawSourceItem(
        source_item_id=f"raw_{item_hash[:16]}",
        source_id=source.source_id,
        source_name=source.name,
        source_type=source.source_type,
        title=title,
        url=url,
        fetched_at=fetched_at,
        published_at=_unix_datetime(post.get("created_utc")),
        summary=summary,
        raw_content=json.dumps(post, ensure_ascii=False, sort_keys=True),
        authors=[str(post["author"])] if post.get("author") else [],
        tags=[tag for tag in [post_subreddit, flair] if tag],
        language=source.language,
        metadata=source_item_metadata(
            source,
            extra={
                "reddit_id": reddit_id,
                "subreddit": post_subreddit,
                "listing": listing,
                "permalink": permalink,
                "external_url": external_url,
                "score": _optional_int(post.get("score")),
                "comments_count": _optional_int(post.get("num_comments")),
                "over_18": bool(post.get("over_18", False)),
                "is_self": bool(post.get("is_self", False)),
                "stickied": bool(post.get("stickied", False)),
            },
        ),
    )


def _subreddit_from_source(source: SourceDefinition, *, subreddit: str | None) -> str:
    if subreddit and subreddit.strip():
        return _ensure_subreddit(subreddit.strip())
    legacy_subreddit = _legacy_reddit_option(source, "subreddit")
    if legacy_subreddit:
        return _ensure_subreddit(legacy_subreddit)
    parsed = urlsplit(source.url)
    parts = [part for part in parsed.path.split("/") if part]
    for index, part in enumerate(parts):
        if part.casefold() == "r" and index + 1 < len(parts):
            return _ensure_subreddit(parts[index + 1])
    raise ValueError("reddit subreddit is required")


def _listing_from_source(source: SourceDefinition, *, listing: str | None) -> str:
    if listing and listing.strip():
        return _ensure_listing(listing.strip())
    legacy_listing = _legacy_reddit_option(source, "listing")
    if legacy_listing:
        return _ensure_listing(legacy_listing)
    return "hot"


def _legacy_reddit_option(source: SourceDefinition, key: str) -> str | None:
    return _optional_text(source.metadata.get(key))


def _time_range_from_source(source: SourceDefinition, *, time_range: str | None) -> str | None:
    if time_range and time_range.strip():
        return _ensure_time_range(time_range)
    legacy_time_range = _legacy_reddit_option(source, "time_range") or _legacy_reddit_option(source, "time")
    if legacy_time_range:
        return _ensure_time_range(legacy_time_range)
    return None


def _ensure_subreddit(value: str) -> str:
    subreddit = value.strip().removeprefix("r/").strip("/")
    if not subreddit or any(char.isspace() for char in subreddit):
        raise ValueError("reddit subreddit is required")
    return subreddit


def _ensure_listing(value: str) -> str:
    listing = value.strip().casefold()
    if listing not in REDDIT_LISTINGS:
        raise ValueError(f"unsupported Reddit listing: {value}")
    return listing


def _ensure_time_range(value: str) -> str:
    time_range = value.strip().casefold()
    if time_range not in REDDIT_TIME_RANGES:
        raise ValueError(f"unsupported Reddit time range: {value}")
    return time_range


def _origin(base_url: str) -> str:
    parsed = urlsplit(base_url or REDDIT_BASE_URL)
    if not parsed.scheme or not parsed.netloc:
        return REDDIT_BASE_URL
    return f"{parsed.scheme}://{parsed.netloc}"


def _reddit_url(value: str | None) -> str | None:
    if value is None:
        return None
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.startswith("/"):
        return f"{REDDIT_BASE_URL}{value}"
    return value


def _unix_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(float(value), tz=UTC)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)
