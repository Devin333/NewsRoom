from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request
from xml.etree import ElementTree

from infrastructure.external.sources.models import RawSourceItem, SourceDefinition, SourceError
from infrastructure.external.sources.diagnostics import (
    SourceFetchResponseMetadata,
    attach_response_metadata_to_error,
    attach_response_metadata_to_items,
    response_metadata_from_http_response,
)
from infrastructure.external.sources.fetch_policy import (
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
from infrastructure.external.sources.metadata import source_item_metadata
from infrastructure.external.sources.errors import classify_source_exception


FetchText = Callable[[str], str]
ARXIV_API_URL = "https://export.arxiv.org/api/query"
ARXIV_NAMESPACE = "http://arxiv.org/schemas/atom"
ARXIV_CONTENT_TYPES = (
    "application/atom+xml",
    "application/xml",
    "text/xml",
)


@dataclass(frozen=True)
class ArxivQuery:
    query: str
    start: int = 0
    max_results: int = 10
    sort_by: str = "submittedDate"
    sort_order: str = "descending"

    def __post_init__(self) -> None:
        if not self.query.strip():
            raise ValueError("arxiv query is required")
        if self.start < 0:
            raise ValueError("start must be non-negative")
        if self.max_results <= 0:
            raise ValueError("max_results must be greater than zero")


class ArxivConnector:
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
        query: str | None = None,
        limit: int | None = None,
    ) -> tuple[list[RawSourceItem], list[SourceError]]:
        policy = effective_fetch_policy(self.fetch_policy, source)
        self._last_response_metadata = None
        try:
            actual_query = _query_from_source(source, query=query)
            request = ArxivQuery(query=actual_query, max_results=limit or 10)
            api_url = build_arxiv_query_url(source.url or ARXIV_API_URL, request)
            rate_limit = self._rate_limiter.reserve(
                api_url,
                limit_per_minute=self.fetch_policy.rate_limit_per_domain_per_minute,
            )
            if not rate_limit.allowed:
                return [], [rate_limited_source_error(source, rate_limit, url=api_url)]
            xml_text = run_with_fetch_retries(
                lambda: self._fetch_source_text(api_url, policy),
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
                        "arXiv API returned an empty response",
                        metadata={"phase": "fetch", "retryable": True, "source_health_affecting": True},
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
                        "empty_arxiv_feed",
                        "arXiv feed contained no paper entries",
                        metadata={"phase": "parse", "retryable": False, "source_health_affecting": False},
                    ),
                    response_metadata,
                )
            ]
        return items, []

    def parse(
        self,
        source: SourceDefinition,
        xml_text: str,
        *,
        limit: int | None = None,
    ) -> list[RawSourceItem]:
        root = ElementTree.fromstring(xml_text)
        if _local_name(root.tag) != "feed":
            raise ValueError(f"unsupported arXiv feed root: {_local_name(root.tag)}")
        fetched_at = datetime.now(UTC)
        items = [_raw_item_from_entry(source, entry, fetched_at) for entry in _children(root, "entry")]
        items = [item for item in items if item is not None]
        return items[:limit] if limit else items

    def _default_fetch_text(self, url: str, policy: SourceFetchPolicy | None = None) -> str:
        policy = policy or self.fetch_policy
        request = Request(url, headers={"User-Agent": policy.user_agent})
        with open_request_with_fetch_policy(request, policy) as response:
            self._last_response_metadata = response_metadata_from_http_response(response, url=url)
            ensure_supported_content_type(self._last_response_metadata.content_type, ARXIV_CONTENT_TYPES)
            body = response.read(policy.max_bytes + 1)
        if len(body) > policy.max_bytes:
            raise ValueError(f"source response exceeds max_bytes: {policy.max_bytes}")
        return body.decode("utf-8", errors="replace")

    def _fetch_source_text(self, url: str, policy: SourceFetchPolicy) -> str:
        if self._uses_default_fetch:
            ensure_robots_allowed(url, policy)
            return self._default_fetch_text(url, policy)
        return self._fetch_text(url)


def build_arxiv_query_url(base_url: str, query: ArxivQuery) -> str:
    params = {
        "search_query": query.query,
        "start": query.start,
        "max_results": query.max_results,
        "sortBy": query.sort_by,
        "sortOrder": query.sort_order,
    }
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{urlencode(params)}"


def _raw_item_from_entry(
    source: SourceDefinition,
    entry: ElementTree.Element,
    fetched_at: datetime,
) -> RawSourceItem | None:
    title = _normalize_text(_child_text(entry, "title"))
    url = _entry_url(entry)
    if not title or not url:
        return None
    arxiv_id = _child_text(entry, "id") or url
    categories = _category_terms(entry)
    item_hash = sha256(f"{source.source_id}|{arxiv_id}".encode("utf-8")).hexdigest()
    return RawSourceItem(
        source_item_id=f"raw_{item_hash[:16]}",
        source_id=source.source_id,
        source_name=source.name,
        source_type=source.source_type,
        title=title,
        url=url,
        fetched_at=fetched_at,
        published_at=_parse_datetime(_child_text(entry, "published") or _child_text(entry, "updated")),
        summary=_normalize_text(_child_text(entry, "summary")),
        raw_content=ElementTree.tostring(entry, encoding="unicode"),
        authors=[name for name in (_child_text(author, "name") for author in _children(entry, "author")) if name],
        tags=categories,
        language=source.language,
        metadata=source_item_metadata(
            source,
            extra={
                "arxiv_id": arxiv_id.rsplit("/", 1)[-1],
                "primary_category": _primary_category(entry),
                "doi": _arxiv_child_text(entry, "doi"),
                "journal_ref": _arxiv_child_text(entry, "journal_ref"),
                "comment": _arxiv_child_text(entry, "comment"),
            },
        ),
    )


def _query_from_source(source: SourceDefinition, *, query: str | None) -> str:
    if query and query.strip():
        return query.strip()
    metadata_query = source.metadata.get("query")
    if isinstance(metadata_query, str) and metadata_query.strip():
        return metadata_query.strip()
    raise ValueError("arxiv query is required")


def _entry_url(entry: ElementTree.Element) -> str | None:
    for child in _children(entry, "link"):
        href = child.attrib.get("href")
        if href and child.attrib.get("rel", "alternate") == "alternate":
            return href.strip()
    return _child_text(entry, "id")


def _category_terms(entry: ElementTree.Element) -> list[str]:
    terms = []
    for child in _children(entry, "category"):
        term = child.attrib.get("term")
        if term:
            terms.append(term)
    return terms


def _primary_category(entry: ElementTree.Element) -> str | None:
    for child in list(entry):
        if child.tag == f"{{{ARXIV_NAMESPACE}}}primary_category":
            return child.attrib.get("term")
    return None


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
        invalid_config_keywords=("query",),
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
        invalid_config_keywords=("query",),
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


def _children(parent: ElementTree.Element, local_name: str) -> list[ElementTree.Element]:
    return [child for child in list(parent) if _local_name(child.tag) == local_name]


def _child_text(parent: ElementTree.Element, local_name: str) -> str | None:
    for child in _children(parent, local_name):
        return child.text.strip() if child.text else None
    return None


def _arxiv_child_text(parent: ElementTree.Element, local_name: str) -> str | None:
    for child in list(parent):
        if child.tag == f"{{{ARXIV_NAMESPACE}}}{local_name}" and child.text:
            return _normalize_text(child.text)
    return None


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _normalize_text(value: str | None) -> str | None:
    if not value:
        return None
    return " ".join(value.split())


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
