from __future__ import annotations

from datetime import datetime, timezone

import pytest

from infrastructure.external.sources.github import GithubRepositoryMetadata
from infrastructure.research import (
    GithubResearchRepositoryAdapter,
    ResearchRepositoryError,
    parse_github_repository_url,
)


UTC = timezone.utc


def test_github_adapter_projects_recorded_repository_metadata() -> None:
    connector = _Connector(_metadata())
    observed_at = datetime(2026, 7, 12, tzinfo=UTC)
    adapter = GithubResearchRepositoryAdapter(connector, clock=lambda: observed_at)

    profile = adapter.fetch_profile("https://github.com/NewsRoom/Runtime.git")

    assert connector.repositories == ["NewsRoom/Runtime"]
    assert profile.repo_url == "https://github.com/NewsRoom/Runtime"
    assert profile.owner == "NewsRoom"
    assert profile.name == "Runtime"
    assert profile.stars == 42
    assert profile.forks == 7
    assert profile.watchers == 11
    assert profile.open_issues == 3
    assert profile.metadata["metrics_source"] == "github_repository_api"
    assert profile.observations[0].stars == 42
    assert profile.observations[0].watchers == 11
    assert profile.observations[0].observed_at == observed_at
    assert profile.observations[0].observed_at != _metadata().updated_at


def test_github_adapter_observation_clock_tracks_sampling_not_resource_update() -> None:
    observed_times = iter(
        [
            datetime(2026, 7, 12, tzinfo=UTC),
            datetime(2026, 7, 14, tzinfo=UTC),
        ]
    )
    adapter = GithubResearchRepositoryAdapter(
        _Connector(_metadata()),
        clock=lambda: next(observed_times),
    )

    first = adapter.fetch_observation("https://github.com/NewsRoom/Runtime")
    second = adapter.fetch_observation("https://github.com/NewsRoom/Runtime")

    assert first.observed_at == datetime(2026, 7, 12, tzinfo=UTC)
    assert second.observed_at == datetime(2026, 7, 14, tzinfo=UTC)
    assert first.observed_at != _metadata().updated_at
    assert second.observed_at != _metadata().updated_at


def test_github_adapter_preserves_missing_watchers_instead_of_copying_stars() -> None:
    adapter = GithubResearchRepositoryAdapter(
        _Connector(_metadata(watchers_count=None))
    )

    profile = adapter.fetch_profile("https://github.com/NewsRoom/Runtime")

    assert profile.stars == 42
    assert profile.watchers is None
    assert profile.observations[0].watchers is None


@pytest.mark.parametrize(
    "url",
    [
        "",
        "git@github.com:owner/repo.git",
        "https://example.com/owner/repo",
        "https://github.com/owner",
        "https://github.com/owner/repo/issues",
        "https://github.com/owner/repo?token=secret",
    ],
)
def test_github_adapter_rejects_non_repository_urls(url: str) -> None:
    with pytest.raises(ResearchRepositoryError):
        parse_github_repository_url(url)


def test_github_adapter_rejects_mismatched_response_identity() -> None:
    connector = _Connector(_metadata(full_name="other/repository"))
    adapter = GithubResearchRepositoryAdapter(connector)

    with pytest.raises(ResearchRepositoryError, match="identity"):
        adapter.fetch_profile("https://github.com/NewsRoom/Runtime")


def test_github_adapter_projects_connector_failure_without_raw_message() -> None:
    error = _SourceError(
        error_type="github_auth_failed",
        error_message="token=TOPSECRET",
        metadata={"retryable": False},
    )
    adapter = GithubResearchRepositoryAdapter(_Connector(None, errors=[error]))

    with pytest.raises(ResearchRepositoryError) as exc:
        adapter.fetch_profile("https://github.com/NewsRoom/Runtime")

    assert "github_auth_failed" in str(exc.value)
    assert "TOPSECRET" not in str(exc.value)


def test_github_adapter_uses_top_level_retryability() -> None:
    error = _SourceError(
        error_type="fetch_timeout",
        error_message="timed out",
        retryable=True,
        metadata={"retryable": False},
    )
    adapter = GithubResearchRepositoryAdapter(_Connector(None, errors=[error]))

    with pytest.raises(ResearchRepositoryError) as exc_info:
        adapter.fetch_profile("https://github.com/NewsRoom/Runtime")

    assert exc_info.value.retryable is True


def test_github_adapter_records_reproducibility_signals_and_revision() -> None:
    connector = _EnrichedConnector(_metadata())
    adapter = GithubResearchRepositoryAdapter(
        connector,
        clock=lambda: datetime(2026, 7, 12, tzinfo=UTC),
    )

    profile = adapter.fetch_profile("https://github.com/NewsRoom/Runtime")

    assert profile.default_branch == "main"
    assert profile.commit_sha == "abc123"
    assert profile.release == "v1.2.0"
    assert profile.has_readme is True
    assert profile.has_requirements is True
    assert profile.has_examples is True
    assert profile.has_training_script is True
    assert profile.has_inference_demo is True
    assert profile.has_model_checkpoint is True
    assert profile.install_instructions_ref
    assert profile.observations[0].metadata["reproducibility"]["source"] == "github_contents_api"
    assert {signal.signal for signal in profile.signals} == {
        "readme",
        "license",
        "install",
        "requirements",
        "examples",
        "training",
        "inference",
        "checkpoint",
    }
    install = next(signal for signal in profile.signals if signal.signal == "install")
    assert install.status == "observed"
    assert install.detection_rule.endswith("/install")
    assert install.matched_refs == [profile.install_instructions_ref]
    assert install.source_snapshot_id in install.source_snapshot_refs
    assert profile.observation_limits == {
        "max_files_checked": 64,
        "max_file_bytes": 256 * 1024,
        "max_total_bytes": 4 * 1024 * 1024,
        "max_directory_depth": 3,
    }
    assert "runnable" not in profile.metadata["reproducibility_observation"]


class _Connector:
    def __init__(self, metadata, *, errors=None) -> None:
        self.metadata = metadata
        self.errors = list(errors or [])
        self.repositories: list[str] = []

    def fetch_repository_metadata(self, source, *, repository):
        self.repositories.append(repository.slug())
        return self.metadata, list(self.errors)


class _EnrichedConnector(_Connector):
    def fetch_repository_file(self, source, *, repository, path, ref=None):
        files = {
            "README.md": "# Runtime\n\npip install runtime\n",
            "requirements.txt": "pydantic\n",
            "examples": "__directory__",
            "training": "__directory__",
            "inference": "__directory__",
            "checkpoints": "__directory__",
        }
        return files.get(path), []

    def fetch_commits(self, source, *, repository, limit=None):
        class _Item:
            metadata = {"sha": "abc123"}

        return [_Item()], []

    def fetch_releases(self, source, *, repository, limit=None):
        class _Item:
            metadata = {"tag_name": "v1.2.0"}

        return [_Item()], []


class _SourceError:
    def __init__(
        self,
        *,
        error_type: str,
        error_message: str,
        metadata: dict,
        retryable: bool | None = None,
    ) -> None:
        self.error_type = error_type
        self.error_message = error_message
        self.metadata = metadata
        self.retryable = retryable


def _metadata(
    *,
    full_name: str = "NewsRoom/Runtime",
    watchers_count: int | None = 11,
) -> GithubRepositoryMetadata:
    return GithubRepositoryMetadata(
        repository_id=123,
        full_name=full_name,
        html_url=f"https://github.com/{full_name}",
        description="A runtime",
        language="Python",
        stargazers_count=42,
        forks_count=7,
        open_issues_count=3,
        archived=False,
        disabled=False,
        visibility="public",
        topics=["agents", "research"],
        pushed_at=datetime(2026, 7, 10, tzinfo=UTC),
        updated_at=datetime(2026, 7, 11, tzinfo=UTC),
        watchers_count=watchers_count,
        default_branch="main",
        license_name="MIT",
    )
