import json
from datetime import UTC, datetime

from domain.sources import SourceDefinition
from sources.connectors.github import GITHUB_API_URL, GithubConnector, GithubRepository


GITHUB_RELEASES = json.dumps(
    [
        {
            "id": 1,
            "url": "https://api.github.com/repos/owner/repo/releases/1",
            "html_url": "https://github.com/owner/repo/releases/tag/v1.0.0",
            "tag_name": "v1.0.0",
            "target_commitish": "main",
            "name": "Version 1.0.0",
            "body": "Release notes for version 1.",
            "draft": False,
            "prerelease": False,
            "created_at": "2026-05-10T10:00:00Z",
            "published_at": "2026-05-11T12:00:00Z",
            "author": {"login": "maintainer"},
        }
    ]
)


def test_github_repository_parses_owner_repo() -> None:
    repository = GithubRepository.parse("owner/repo")

    assert repository.owner == "owner"
    assert repository.name == "repo"
    assert repository.slug() == "owner/repo"


def test_github_connector_parses_releases() -> None:
    source = _source()

    items = GithubConnector().parse_releases(source, GITHUB_RELEASES, repository="owner/repo")

    assert len(items) == 1
    item = items[0]
    assert item.source_type.value == "github"
    assert item.title == "Version 1.0.0"
    assert item.url == "https://github.com/owner/repo/releases/tag/v1.0.0"
    assert item.published_at == datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
    assert item.authors == ["maintainer"]
    assert item.tags == ["v1.0.0"]
    assert item.metadata["repository"] == "owner/repo"
    assert item.metadata["tag_name"] == "v1.0.0"
    assert item.metadata["prerelease"] is False


def test_github_connector_fetch_builds_release_url() -> None:
    captured = {}

    def fetch_text(url: str) -> str:
        captured["url"] = url
        return GITHUB_RELEASES

    items, errors = GithubConnector(fetch_text=fetch_text).fetch_releases(
        _source(),
        repository="owner/repo",
        limit=1,
    )

    assert errors == []
    assert len(items) == 1
    assert captured["url"] == f"{GITHUB_API_URL}/repos/owner/repo/releases?per_page=1"


def test_github_connector_returns_empty_release_error() -> None:
    items, errors = GithubConnector(fetch_text=lambda url: "[]").fetch_releases(
        _source(),
        repository="owner/repo",
        limit=1,
    )

    assert items == []
    assert errors[0].error_type == "empty_github_releases"
    assert errors[0].metadata["phase"] == "parse"


def test_github_connector_returns_invalid_repository_error() -> None:
    items, errors = GithubConnector(fetch_text=lambda url: GITHUB_RELEASES).fetch_releases(
        _source(),
        repository="bad",
    )

    assert items == []
    assert errors[0].error_type == "invalid_source_config"
    assert errors[0].metadata["phase"] == "fetch"


def test_github_connector_default_fetch_rejects_unsupported_content_type(monkeypatch) -> None:
    class Headers:
        def get_content_type(self):
            return "text/html"

    class Response:
        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self, size):
            return GITHUB_RELEASES.encode("utf-8")

    def fake_open_request(request, policy):
        return Response()

    monkeypatch.setattr("sources.connectors.github.open_request_with_fetch_policy", fake_open_request)

    items, errors = GithubConnector().fetch_releases(
        _source(),
        repository="owner/repo",
        limit=1,
    )

    assert items == []
    assert errors[0].error_type == "unsupported_content_type"
    assert errors[0].metadata["phase"] == "fetch"
    assert errors[0].metadata["content_type"] == "text/html"
    assert errors[0].metadata["retryable"] is False
    assert errors[0].metadata["source_health_affecting"] is False
    assert "application/vnd.github+json" in errors[0].metadata["supported_content_types"]


def _source() -> SourceDefinition:
    return SourceDefinition(
        source_id="github",
        name="GitHub",
        source_type="github",
        url=GITHUB_API_URL,
        reliability="high",
        authority_score=0.9,
        language="en",
    )
