from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Callable, Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from domain.sources import RawSourceItem, SourceDefinition, SourceError
from sources.connectors.feed import SourceFetchPolicy


FetchText = Callable[[str], str]
GITHUB_API_URL = "https://api.github.com"


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


class GithubConnector:
    def __init__(
        self,
        fetch_text: FetchText | None = None,
        *,
        fetch_policy: SourceFetchPolicy | None = None,
    ) -> None:
        self.fetch_policy = fetch_policy or SourceFetchPolicy()
        self._fetch_text = fetch_text or self._default_fetch_text

    def fetch_releases(
        self,
        source: SourceDefinition,
        *,
        repository: str | GithubRepository | None = None,
        limit: int | None = None,
    ) -> tuple[list[RawSourceItem], list[SourceError]]:
        try:
            repo = _repository_from_source(source, repository=repository)
            api_url = build_github_releases_url(source.url or GITHUB_API_URL, repo, limit=limit or 10)
            payload = self._fetch_text(api_url)
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

    def _default_fetch_text(self, url: str) -> str:
        request = Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": self.fetch_policy.user_agent,
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urlopen(request, timeout=self.fetch_policy.timeout_seconds) as response:
            body = response.read(self.fetch_policy.max_bytes + 1)
        if len(body) > self.fetch_policy.max_bytes:
            raise ValueError(f"source response exceeds max_bytes: {self.fetch_policy.max_bytes}")
        return body.decode("utf-8", errors="replace")


def build_github_releases_url(base_url: str, repository: GithubRepository, *, limit: int) -> str:
    base = base_url.rstrip("/")
    params = urlencode({"per_page": limit})
    return f"{base}/repos/{repository.owner}/{repository.name}/releases?{params}"


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
        metadata={
            "repository": repository.slug(),
            "release_id": release.get("id"),
            "tag_name": tag_name,
            "target_commitish": release.get("target_commitish"),
            "draft": bool(release.get("draft", False)),
            "prerelease": bool(release.get("prerelease", False)),
            "api_url": release.get("url"),
            "source_reliability": source.reliability.value,
            "source_authority_score": source.authority_score,
        },
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
    if isinstance(exc, HTTPError):
        metadata["status_code"] = exc.code
    return _source_error(source, error_type, str(exc), metadata=metadata)


def _taxonomy_for_exception(exc: Exception, *, phase: str) -> tuple[str, bool]:
    if phase == "parse":
        return "parse_error", False
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


def _normalize_text(value: Any) -> str | None:
    if not value:
        return None
    return " ".join(str(value).split())
