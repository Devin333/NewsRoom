from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Callable
from urllib.parse import urlsplit

from business.research.domain.code_repository import (
    CodeRepositoryObservation,
    CodeRepositoryProfile,
)
from infrastructure.external.sources.github import (
    GITHUB_API_URL,
    GithubConnector,
    GithubRepository,
)
from infrastructure.external.sources.models import (
    SourceDefinition,
    SourceReliability,
    SourceType,
)
from infrastructure.research.errors import (
    ResearchRepositoryError,
    summarize_source_failures,
)


UTC = timezone.utc
_GITHUB_HOSTS = {"github.com", "www.github.com"}


class GithubResearchRepositoryAdapter:
    """Map official GitHub repository metadata into Research code profiles."""

    def __init__(
        self,
        connector: GithubConnector | Any | None = None,
        *,
        api_url: str = GITHUB_API_URL,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._connector = connector or GithubConnector()
        self._api_url = str(api_url).strip() or GITHUB_API_URL
        self._clock = clock or (lambda: datetime.now(UTC))

    def fetch_profile(self, repo_url: str) -> CodeRepositoryProfile:
        repository, canonical_url = parse_github_repository_url(repo_url)
        source = SourceDefinition(
            source_id=f"research-github-{_stable_suffix(repository.slug())}",
            name=f"GitHub {repository.slug()}",
            source_type=SourceType.GITHUB,
            url=self._api_url,
            reliability=SourceReliability.HIGH,
            authority_score=1.0,
            metadata={"repository": repository.slug()},
        )
        metadata, errors = self._connector.fetch_repository_metadata(
            source,
            repository=repository,
        )
        if errors or metadata is None:
            failure = summarize_source_failures(
                errors,
                default_error_type="repository_fetch_failed",
            )
            raise ResearchRepositoryError(
                "GitHub repository metadata is unavailable "
                f"({','.join(failure.error_types)})",
                retryable=failure.retryable,
            )
        if metadata.full_name.casefold() != repository.slug().casefold():
            raise ResearchRepositoryError(
                "GitHub repository response identity does not match the request"
            )
        observed_at = self._clock()
        observation = CodeRepositoryObservation(
            repo_url=canonical_url,
            observed_at=observed_at,
            stars=metadata.stargazers_count,
            forks=metadata.forks_count,
            watchers=metadata.watchers_count,
            metadata={
                "metrics_source": "github_repository_api",
                "repository_id": metadata.repository_id,
            },
        )
        return CodeRepositoryProfile(
            repo_url=canonical_url,
            owner=repository.owner,
            name=repository.name,
            stars=metadata.stargazers_count,
            forks=metadata.forks_count,
            watchers=metadata.watchers_count,
            open_issues=metadata.open_issues_count,
            last_commit_at=metadata.pushed_at,
            observations=[observation],
            metadata={
                "metrics_source": "github_repository_api",
                "repository_id": metadata.repository_id,
                "description": metadata.description,
                "language": metadata.language,
                "topics": list(metadata.topics),
                "archived": metadata.archived,
                "disabled": metadata.disabled,
                "visibility": metadata.visibility,
                "github_updated_at": (
                    metadata.updated_at.isoformat() if metadata.updated_at else None
                ),
            },
        )

    def fetch_observation(self, repo_url: str) -> CodeRepositoryObservation:
        profile = self.fetch_profile(repo_url)
        if not profile.observations:
            raise ResearchRepositoryError("GitHub repository observation is unavailable")
        return profile.observations[-1]


def parse_github_repository_url(value: str) -> tuple[GithubRepository, str]:
    text = str(value or "").strip()
    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in _GITHUB_HOSTS:
        raise ResearchRepositoryError("code repository must be an HTTPS GitHub URL")
    if parsed.query or parsed.fragment:
        raise ResearchRepositoryError("GitHub repository URL must not contain query or fragment")
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) != 2:
        raise ResearchRepositoryError("GitHub repository URL must identify owner/repository")
    owner, name = parts
    if name.endswith(".git"):
        name = name[:-4]
    if not owner or not name or owner in {".", ".."} or name in {".", ".."}:
        raise ResearchRepositoryError("GitHub repository identity is invalid")
    repository = GithubRepository(owner=owner, name=name)
    return repository, f"https://github.com/{repository.slug()}"


def _stable_suffix(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()[:16]


__all__ = ["GithubResearchRepositoryAdapter", "parse_github_repository_url"]
