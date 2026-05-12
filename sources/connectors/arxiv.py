from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from domain.sources import RawSourceItem, SourceDefinition, SourceError
from sources.connectors.fetch_policy import (
    DomainRateLimiter,
    SourceFetchPolicy,
    fetch_attempts,
    rate_limited_source_error,
    run_with_fetch_retries,
)
from sources.connectors.metadata import source_item_metadata


FetchText = Callable[[str], str]
ARXIV_API_URL = "https://export.arxiv.org/api/query"
ARXIV_NAMESPACE = "http://arxiv.org/schemas/atom"


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
        self._fetch_text = fetch_text or self._default_fetch_text

    def fetch(
        self,
        source: SourceDefinition,
        *,
        query: str | None = None,
        limit: int | None = None,
    ) -> tuple[list[RawSourceItem], list[SourceError]]:
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
                lambda: self._fetch_text(api_url),
                self.fetch_policy,
            )
        except Exception as exc:
            return [], [_exception_source_error(source, exc, phase="fetch")]

        if not xml_text.strip():
            return [], [
                _source_error(
                    source,
                    "empty_source_response",
                    "arXiv API returned an empty response",
                    metadata={"phase": "fetch", "retryable": True, "source_health_affecting": True},
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
                    "empty_arxiv_feed",
                    "arXiv feed contained no paper entries",
                    metadata={"phase": "parse", "retryable": False, "source_health_affecting": False},
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

    def _default_fetch_text(self, url: str) -> str:
        request = Request(url, headers={"User-Agent": self.fetch_policy.user_agent})
        with urlopen(request, timeout=self.fetch_policy.timeout_seconds) as response:
            body = response.read(self.fetch_policy.max_bytes + 1)
        if len(body) > self.fetch_policy.max_bytes:
            raise ValueError(f"source response exceeds max_bytes: {self.fetch_policy.max_bytes}")
        return body.decode("utf-8", errors="replace")


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
    if isinstance(exc, HTTPError):
        metadata["status_code"] = exc.code
    attempts = fetch_attempts(exc)
    if attempts is not None:
        metadata["attempts"] = attempts
    return _source_error(source, error_type, str(exc), metadata=metadata)


def _taxonomy_for_exception(exc: Exception, *, phase: str) -> tuple[str, bool]:
    if phase == "parse":
        return "parse_error", False
    if isinstance(exc, ValueError) and "query" in str(exc):
        return "invalid_source_config", False
    if isinstance(exc, HTTPError):
        if 400 <= exc.code < 500:
            return "fetch_http_4xx", exc.code in {408, 409, 425, 429}
        if exc.code >= 500:
            return "fetch_http_5xx", True
        return "fetch_connection_error", True
    if _is_timeout_exception(exc):
        return "fetch_timeout", True
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
