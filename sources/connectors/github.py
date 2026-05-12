from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Callable, Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
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


FetchText = Callable[[str], str]
GITHUB_API_URL = "https://api.github.com"
GITHUB_CONTENT_TYPES = (
    "application/json",
    "application/vnd.github+json",
)


@dataclass(frozen=True)
class GithubRepository:
    owner: str
    name: str

    def __post_init__(self) -> None:
        if not self.owner.strip():
            raise ValueError("github repository owner is required")
        if not self.name.strip():
            raise ValueError("github repository name is required")

    @classmethod
    def parse(cls, value: str) -> GithubRepository:
        if "/" not in value:
            raise ValueError("github repository must use owner/repo format")
        owner, name = value.split("/", 1)
        return cls(owner=owner.strip(), name=name.strip())

    def slug(self) -> str:
        return f"{self.owner}/{self.name}"


@dataclass(frozen=True)
class GithubRepositorySearchResult:
    repository_id: int | None
    full_name: str
    html_url: str
    description: str | None
    language: str | None
    stargazers_count: int
    forks_count: int
    open_issues_count: int
    archived: bool
    disabled: bool
    visibility: str | None
    topics: list[str]
    updated_at: datetime | None
    score: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository_id": self.repository_id,
            "full_name": self.full_name,
            "html_url": self.html_url,
            "description": self.description,
            "language": self.language,
            "stargazers_count": self.stargazers_count,
            "forks_count": self.forks_count,
            "open_issues_count": self.open_issues_count,
            "archived": self.archived,
            "disabled": self.disabled,
            "visibility": self.visibility,
            "topics": list(self.topics),
            "updated_at": _dt(self.updated_at),
            "score": self.score,
        }


class GithubConnector:
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

    def fetch_releases(
        self,
        source: SourceDefinition,
        *,
        repository: str | GithubRepository | None = None,
        limit: int | None = None,
    ) -> tuple[list[RawSourceItem], list[SourceError]]:
        policy = effective_fetch_policy(self.fetch_policy, source)
        try:
            repo = _repository_from_source(source, repository=repository)
            api_url = build_github_releases_url(source.url or GITHUB_API_URL, repo, limit=limit or 10)
            rate_limit = self._rate_limiter.reserve(
                api_url,
                limit_per_minute=self.fetch_policy.rate_limit_per_domain_per_minute,
            )
            if not rate_limit.allowed:
                return [], [rate_limited_source_error(source, rate_limit, url=api_url)]
            payload = run_with_fetch_retries(
                lambda: self._fetch_source_text(api_url, policy),
                policy,
            )
        except Exception as exc:
            return [], [_exception_source_error(source, exc, phase="fetch")]

        if not payload.strip():
            return [], [
                _source_error(
                    source,
                    "empty_source_response",
                    "GitHub API returned an empty response",
                    metadata={"phase": "fetch", "retryable": True, "source_health_affecting": True},
                )
            ]

        try:
            items = self.parse_releases(source, payload, repository=repo, limit=limit)
        except Exception as exc:
            return [], [_exception_source_error(source, exc, phase="parse")]

        if not items:
            return [], [
                _source_error(
                    source,
                    "empty_github_releases",
                    "GitHub repository returned no releases",
                    metadata={"phase": "parse", "retryable": False, "source_health_affecting": False},
                )
            ]
        return items, []

    def search_repositories(
        self,
        source: SourceDefinition,
        *,
        query: str,
        limit: int | None = None,
        sort: str | None = None,
        order: str | None = None,
    ) -> tuple[list[GithubRepositorySearchResult], list[SourceError]]:
        policy = effective_fetch_policy(self.fetch_policy, source)
        try:
            query_text = query.strip()
            if not query_text:
                raise ValueError("github repository search query is required")
            api_url = build_github_repository_search_url(
                source.url or GITHUB_API_URL,
                query_text,
                limit=limit or 10,
                sort=sort,
                order=order,
            )
            rate_limit = self._rate_limiter.reserve(
                api_url,
                limit_per_minute=self.fetch_policy.rate_limit_per_domain_per_minute,
            )
            if not rate_limit.allowed:
                return [], [rate_limited_source_error(source, rate_limit, url=api_url)]
            payload = run_with_fetch_retries(
                lambda: self._fetch_source_text(api_url, policy),
                policy,
            )
        except Exception as exc:
            return [], [_exception_source_error(source, exc, phase="fetch")]

        if not payload.strip():
            return [], [
                _source_error(
                    source,
                    "empty_source_response",
                    "GitHub API returned an empty response",
                    metadata={"phase": "fetch", "retryable": True, "source_health_affecting": True},
                )
            ]

        try:
            repositories = self.parse_repository_search(payload, limit=limit)
        except Exception as exc:
            return [], [_exception_source_error(source, exc, phase="parse")]

        if not repositories:
            return [], [
                _source_error(
                    source,
                    "empty_github_repositories",
                    "GitHub repository search returned no repositories",
                    metadata={"phase": "parse", "retryable": False, "source_health_affecting": False},
                )
            ]
        return repositories, []

    def parse_releases(
        self,
        source: SourceDefinition,
        content: str,
        *,
        repository: str | GithubRepository | None = None,
        limit: int | None = None,
    ) -> list[RawSourceItem]:
        payload = json.loads(content)
        if not isinstance(payload, list):
            raise ValueError("GitHub releases response must be a JSON array")
        repo = _repository_from_source(source, repository=repository)
        fetched_at = datetime.now(UTC)
        items = [
            _raw_item_from_release(source=source, repository=repo, release=release, fetched_at=fetched_at)
            for release in payload
            if isinstance(release, dict)
        ]
        items = [item for item in items if item is not None]
        return items[:limit] if limit else items

    def parse_repository_search(
        self,
        content: str,
        *,
        limit: int | None = None,
    ) -> list[GithubRepositorySearchResult]:
        payload = json.loads(content)
        if not isinstance(payload, dict):
            raise ValueError("GitHub repository search response must be a JSON object")
        items = payload.get("items")
        if not isinstance(items, list):
            raise ValueError("GitHub repository search response items must be an array")
        repositories = [
            _repository_search_result(item)
            for item in items
            if isinstance(item, dict)
        ]
        repositories = [repository for repository in repositories if repository is not None]
        return repositories[:limit] if limit else repositories

    def _default_fetch_text(self, url: str) -> str:
        request = Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": self.fetch_policy.user_agent,
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with open_request_with_fetch_policy(request, self.fetch_policy) as response:
            headers = getattr(response, "headers", None)
            content_type = headers.get_content_type() if headers is not None else None
            ensure_supported_content_type(content_type, GITHUB_CONTENT_TYPES)
            body = response.read(self.fetch_policy.max_bytes + 1)
        if len(body) > self.fetch_policy.max_bytes:
            raise ValueError(f"source response exceeds max_bytes: {self.fetch_policy.max_bytes}")
        return body.decode("utf-8", errors="replace")

    def _fetch_source_text(self, url: str, policy: SourceFetchPolicy) -> str:
        if self._uses_default_fetch:
            ensure_robots_allowed(url, policy)
        return self._fetch_text(url)


def build_github_releases_url(base_url: str, repository: GithubRepository, *, limit: int) -> str:
    base = base_url.rstrip("/")
    params = urlencode({"per_page": limit})
    return f"{base}/repos/{repository.owner}/{repository.name}/releases?{params}"


def build_github_repository_search_url(
    base_url: str,
    query: str,
    *,
    limit: int,
    sort: str | None = None,
    order: str | None = None,
) -> str:
    base = base_url.rstrip("/")
    params: dict[str, Any] = {"q": query, "per_page": limit}
    if sort:
        params["sort"] = sort
    if order:
        params["order"] = order
    return f"{base}/search/repositories?{urlencode(params)}"


def _repository_search_result(item: dict[str, Any]) -> GithubRepositorySearchResult | None:
    full_name = item.get("full_name")
    html_url = item.get("html_url")
    if not full_name or not html_url:
        return None
    return GithubRepositorySearchResult(
        repository_id=_optional_int(item.get("id")),
        full_name=str(full_name),
        html_url=str(html_url),
        description=_optional_text(item.get("description")),
        language=_optional_text(item.get("language")),
        stargazers_count=_int_or_zero(item.get("stargazers_count")),
        forks_count=_int_or_zero(item.get("forks_count")),
        open_issues_count=_int_or_zero(item.get("open_issues_count")),
        archived=bool(item.get("archived", False)),
        disabled=bool(item.get("disabled", False)),
        visibility=_optional_text(item.get("visibility")),
        topics=[str(topic) for topic in item.get("topics") or []],
        updated_at=_parse_datetime(item.get("updated_at")),
        score=_optional_float(item.get("score")),
    )


def _raw_item_from_release(
    *,
    source: SourceDefinition,
    repository: GithubRepository,
    release: dict[str, Any],
    fetched_at: datetime,
) -> RawSourceItem | None:
    url = release.get("html_url")
    tag_name = release.get("tag_name")
    title = release.get("name") or tag_name
    if not url or not title:
        return None
    item_hash = sha256(f"{source.source_id}|{repository.slug()}|{url}".encode("utf-8")).hexdigest()
    author = release.get("author") if isinstance(release.get("author"), dict) else {}
    return RawSourceItem(
        source_item_id=f"raw_{item_hash[:16]}",
        source_id=source.source_id,
        source_name=source.name,
        source_type=source.source_type,
        title=str(title).strip(),
        url=str(url).strip(),
        fetched_at=fetched_at,
        published_at=_parse_datetime(release.get("published_at") or release.get("created_at")),
        summary=_normalize_text(release.get("body")),
        raw_content=json.dumps(release, ensure_ascii=False, sort_keys=True),
        authors=[str(author["login"])] if author.get("login") else [],
        tags=[str(tag_name)] if tag_name else [],
        language=source.language,
        metadata=source_item_metadata(
            source,
            extra={
                "repository": repository.slug(),
                "release_id": release.get("id"),
                "tag_name": tag_name,
                "target_commitish": release.get("target_commitish"),
                "draft": bool(release.get("draft", False)),
                "prerelease": bool(release.get("prerelease", False)),
                "api_url": release.get("url"),
            },
        ),
    )


def _repository_from_source(
    source: SourceDefinition,
    *,
    repository: str | GithubRepository | None,
) -> GithubRepository:
    if isinstance(repository, GithubRepository):
        return repository
    if isinstance(repository, str) and repository.strip():
        return GithubRepository.parse(repository)
    metadata_repository = source.metadata.get("repository")
    if isinstance(metadata_repository, str) and metadata_repository.strip():
        return GithubRepository.parse(metadata_repository)
    raise ValueError("github repository must use owner/repo format")


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
    if isinstance(exc, UnsupportedContentTypeError):
        return "unsupported_content_type", False
    if isinstance(exc, TooManyRedirectsError):
        return "too_many_redirects", False
    if isinstance(exc, RobotsDisallowedError):
        return "robots_disallowed", False
    if isinstance(exc, ValueError) and "repository" in str(exc):
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


def _dt(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _int_or_zero(value: Any) -> int:
    if value is None:
        return 0
    return int(value)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _normalize_text(value: Any) -> str | None:
    if not value:
        return None
    return " ".join(str(value).split())
