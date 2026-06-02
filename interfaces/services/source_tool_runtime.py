from __future__ import annotations

from collections.abc import Sequence
from urllib.parse import urlsplit
from urllib.request import Request

from business.foundation.models.source import (
    RawSourceItem,
    SourceDefinition,
    SourceError,
    SourceFetchPolicy as BusinessSourceFetchPolicy,
    SourceReliability as BusinessSourceReliability,
    SourceType as BusinessSourceType,
)
from business.layers.signal.source_tool_runtime import (
    FetchText,
    SourceTextFetchResult,
)
from infrastructure.external.sources import (
    DomainRateLimiter,
    FeedConnector,
    HtmlConnector,
    ManualConnector,
)
from infrastructure.external.sources.fetch_policy import (
    SourceFetchPolicy as InfraSourceFetchPolicy,
    ensure_robots_allowed,
    open_request_with_fetch_policy,
    run_with_fetch_retries,
)
from infrastructure.external.sources.models import (
    RawSourceItem as InfraRawSourceItem,
    SourceDefinition as InfraSourceDefinition,
    SourceError as InfraSourceError,
    SourceReliability as InfraSourceReliability,
    SourceType as InfraSourceType,
)


class InfrastructureSourceToolRuntime:
    def __init__(self, *, fetch_text: FetchText | None = None) -> None:
        self._fetch_text = fetch_text
        self._rate_limiter = DomainRateLimiter()

    def fetch_text(
        self,
        url: str,
        policy: BusinessSourceFetchPolicy,
    ) -> SourceTextFetchResult:
        _ensure_http_url(url)
        infra_policy = _infra_fetch_policy(policy)
        if self._fetch_text is not None:
            return run_with_fetch_retries(
                lambda: _fetch_with_callable(self._fetch_text, url, infra_policy),
                infra_policy,
            )
        return run_with_fetch_retries(lambda: _default_fetch_text(url, infra_policy), infra_policy)

    def parse_feed(
        self,
        source: SourceDefinition,
        content: str,
        *,
        limit: int | None = None,
    ) -> list[RawSourceItem]:
        items = FeedConnector().parse(_infra_source(source), content, limit=limit)
        return [_business_raw_source_item(item) for item in items]

    def parse_html(
        self,
        source: SourceDefinition,
        content: str,
        *,
        limit: int | None = None,
    ) -> list[RawSourceItem]:
        items = HtmlConnector().parse(_infra_source(source), content, limit=limit)
        return [_business_raw_source_item(item) for item in items]

    def fetch_manual(
        self,
        source: SourceDefinition,
        *,
        records: Sequence[dict[str, object]],
        limit: int | None = None,
    ) -> tuple[list[RawSourceItem], list[SourceError]]:
        items, errors = ManualConnector().fetch(
            _infra_source(source),
            records=records,
            limit=limit,
        )
        return (
            [_business_raw_source_item(item) for item in items],
            [_business_source_error(error) for error in errors],
        )

    def fetch_official_blog(
        self,
        source: SourceDefinition,
        *,
        policy: BusinessSourceFetchPolicy,
        limit: int | None = None,
    ) -> tuple[list[RawSourceItem], list[SourceError]]:
        infra_source = _infra_source(source)
        infra_policy = _infra_fetch_policy(policy)
        connector = _official_blog_connector(
            infra_source,
            fetch_text=self._fetch_text,
            policy=infra_policy,
            rate_limiter=self._rate_limiter,
        )
        items, errors = connector.fetch(infra_source, limit=limit)
        return (
            [_business_raw_source_item(item) for item in items],
            [_business_source_error(error) for error in errors],
        )


def default_source_tool_runtime(*, fetch_text: FetchText | None = None) -> InfrastructureSourceToolRuntime:
    return InfrastructureSourceToolRuntime(fetch_text=fetch_text)


def _fetch_with_callable(
    fetch_text: FetchText,
    url: str,
    policy: InfraSourceFetchPolicy,
) -> SourceTextFetchResult:
    content = fetch_text(url)
    if len(content.encode("utf-8")) > policy.max_bytes:
        raise ValueError(f"source response exceeds max_bytes: {policy.max_bytes}")
    return SourceTextFetchResult(content=content)


def _default_fetch_text(url: str, policy: InfraSourceFetchPolicy) -> SourceTextFetchResult:
    ensure_robots_allowed(url, policy)
    request = Request(url, headers={"User-Agent": policy.user_agent})
    with open_request_with_fetch_policy(request, policy) as response:
        body = response.read(policy.max_bytes + 1)
        status_code = getattr(response, "status", None)
        headers = getattr(response, "headers", None)
        content_type = headers.get_content_type() if headers is not None else None
    if len(body) > policy.max_bytes:
        raise ValueError(f"source response exceeds max_bytes: {policy.max_bytes}")
    return SourceTextFetchResult(
        content=body.decode("utf-8", errors="replace"),
        status_code=int(status_code) if status_code is not None else None,
        content_type=content_type,
    )


def _official_blog_connector(
    source: InfraSourceDefinition,
    *,
    fetch_text: FetchText | None,
    policy: InfraSourceFetchPolicy,
    rate_limiter: DomainRateLimiter,
) -> FeedConnector | HtmlConnector:
    if _is_html_backed_source_type(source.source_type):
        return HtmlConnector(
            fetch_text=_policy_fetch_text(fetch_text, policy),
            fetch_policy=policy,
            rate_limiter=rate_limiter,
        )
    return FeedConnector(
        fetch_text=_policy_fetch_text(fetch_text, policy),
        fetch_policy=policy,
        rate_limiter=rate_limiter,
    )


def _policy_fetch_text(
    fetch_text: FetchText | None,
    policy: InfraSourceFetchPolicy,
) -> FetchText | None:
    if fetch_text is None:
        return None

    def wrapped(url: str) -> str:
        content = fetch_text(url)
        if len(content.encode("utf-8")) > policy.max_bytes:
            raise ValueError(f"source response exceeds max_bytes: {policy.max_bytes}")
        return content

    return wrapped


def _infra_source(source: SourceDefinition) -> InfraSourceDefinition:
    return InfraSourceDefinition(
        source_id=source.source_id,
        name=source.name,
        source_type=InfraSourceType(BusinessSourceType(source.source_type).value),
        url=source.url,
        reliability=InfraSourceReliability(BusinessSourceReliability(source.reliability).value),
        authority_score=source.authority_score,
        enabled=source.enabled,
        fetch_interval_seconds=source.fetch_interval_seconds,
        respect_robots=source.respect_robots,
        user_agent=source.user_agent,
        topics=list(source.topics),
        category=source.category,
        language=source.language,
        region=source.region,
        metadata=dict(source.metadata),
    )


def _infra_fetch_policy(
    policy: BusinessSourceFetchPolicy | InfraSourceFetchPolicy,
) -> InfraSourceFetchPolicy:
    if isinstance(policy, InfraSourceFetchPolicy):
        return policy
    return InfraSourceFetchPolicy(
        timeout_seconds=policy.timeout_seconds,
        max_bytes=policy.max_bytes,
        max_redirects=policy.max_redirects,
        user_agent=policy.user_agent,
        respect_robots=policy.respect_robots,
        rate_limit_per_domain_per_minute=policy.rate_limit_per_domain_per_minute,
        retry_times=policy.retry_times,
        retry_on_status_codes=tuple(policy.retry_on_status_codes),
    )


def _business_raw_source_item(item: InfraRawSourceItem) -> RawSourceItem:
    return RawSourceItem(
        source_item_id=item.source_item_id,
        source_id=item.source_id,
        source_name=item.source_name,
        source_type=BusinessSourceType(item.source_type).value,
        title=item.title,
        url=item.url,
        fetched_at=item.fetched_at,
        published_at=item.published_at,
        summary=item.summary,
        raw_content=item.raw_content,
        raw_artifact_ref=item.raw_artifact_ref,
        parse_artifact_ref=item.parse_artifact_ref,
        authors=list(item.authors),
        tags=list(item.tags),
        language=item.language,
        lineage=item.lineage.to_dict() if item.lineage else None,
        metadata=dict(item.metadata),
    )


def _business_source_error(error: InfraSourceError) -> SourceError:
    return SourceError(
        source_id=error.source_id,
        source_name=error.source_name,
        error_type=error.error_type,
        error_message=error.error_message,
        url=error.url,
        retryable=error.retryable,
        request_ref=error.request_ref,
        response_ref=error.response_ref,
        occurred_at=error.occurred_at,
        metadata=dict(error.metadata),
    )


def _is_html_backed_source_type(source_type: InfraSourceType | str) -> bool:
    return InfraSourceType(source_type) in {
        InfraSourceType.HTML,
        InfraSourceType.OFFICIAL_BLOG,
        InfraSourceType.WEB_PAGE,
    }


def _ensure_http_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("source URL must use http or https")


__all__ = [
    "InfrastructureSourceToolRuntime",
    "default_source_tool_runtime",
]
