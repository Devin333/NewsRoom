import json
from datetime import UTC, datetime

from business.foundation.models.source import SourceDefinition
from infrastructure.external.sources.github import GITHUB_API_URL, GithubConnector, GithubRepository


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

GITHUB_COMMITS = json.dumps(
    [
        {
            "sha": "abcdef1234567890",
            "html_url": "https://github.com/owner/repo/commit/abcdef1",
            "url": "https://api.github.com/repos/owner/repo/commits/abcdef1",
            "commit": {
                "message": "Add source pipeline\n\nDetails",
                "author": {"name": "Alice", "date": "2026-05-11T10:00:00Z"},
            },
            "author": {"login": "alice"},
        }
    ]
)

GITHUB_ISSUES = json.dumps(
    [
        {
            "number": 7,
            "html_url": "https://github.com/owner/repo/issues/7",
            "url": "https://api.github.com/repos/owner/repo/issues/7",
            "title": "Bug in source pipeline",
            "body": "Issue body",
            "state": "open",
            "created_at": "2026-05-10T10:00:00Z",
            "user": {"login": "reporter"},
            "labels": [{"name": "bug"}],
        },
        {
            "number": 8,
            "html_url": "https://github.com/owner/repo/pull/8",
            "title": "PR surfaced through issues API",
            "pull_request": {"url": "https://api.github.com/pulls/8"},
        },
    ]
)

GITHUB_PULLS = json.dumps(
    [
        {
            "number": 8,
            "html_url": "https://github.com/owner/repo/pull/8",
            "url": "https://api.github.com/repos/owner/repo/pulls/8",
            "title": "Improve connector",
            "body": "Pull request body",
            "state": "open",
            "created_at": "2026-05-09T10:00:00Z",
            "user": {"login": "contributor"},
            "labels": [{"name": "enhancement"}],
        }
    ]
)

GITHUB_ADVISORIES = json.dumps(
    [
        {
            "ghsa_id": "GHSA-xxxx-yyyy",
            "html_url": "https://github.com/advisories/GHSA-xxxx-yyyy",
            "url": "https://api.github.com/advisories/GHSA-xxxx-yyyy",
            "summary": "Critical package issue",
            "description": "Security advisory body",
            "severity": "critical",
            "published_at": "2026-05-08T10:00:00Z",
        }
    ]
)

GITHUB_SEARCH = json.dumps(
    {
        "items": [
            {
                "id": 1,
                "full_name": "owner/repo",
                "html_url": "https://github.com/owner/repo",
                "description": "Repository description",
                "language": "Python",
                "stargazers_count": 123,
                "forks_count": 4,
                "open_issues_count": 5,
                "archived": False,
                "disabled": False,
                "visibility": "public",
                "topics": ["ai", "news"],
                "updated_at": "2026-05-11T10:00:00Z",
                "score": 1.0,
            }
        ]
    }
)

GITHUB_DISCUSSIONS = json.dumps(
    {
        "data": {
            "repository": {
                "discussions": {
                    "nodes": [
                        {
                            "id": "D_kwDO",
                            "number": 12,
                            "title": "Runtime architecture discussion",
                            "url": "https://github.com/owner/repo/discussions/12",
                            "bodyText": "Discussion body",
                            "createdAt": "2026-05-10T10:00:00Z",
                            "updatedAt": "2026-05-11T10:00:00Z",
                            "author": {"login": "maintainer"},
                            "category": {"name": "Ideas"},
                            "comments": {"totalCount": 3},
                        }
                    ]
                }
            }
        }
    }
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


def test_github_connector_fetches_commits() -> None:
    captured = {}

    def fetch_text(url: str) -> str:
        captured["url"] = url
        return GITHUB_COMMITS

    items, errors = GithubConnector(fetch_text=fetch_text).fetch_commits(
        _source(),
        repository="owner/repo",
        limit=1,
    )

    assert errors == []
    assert captured["url"] == f"{GITHUB_API_URL}/repos/owner/repo/commits?per_page=1"
    assert items[0].title == "Add source pipeline"
    assert items[0].authors == ["alice"]
    assert items[0].metadata["github_surface"] == "commits"
    assert items[0].metadata["sha"] == "abcdef1234567890"


def test_github_connector_fetches_issues_without_pull_requests() -> None:
    items, errors = GithubConnector(fetch_text=lambda url: GITHUB_ISSUES).fetch_issues(
        _source(),
        repository="owner/repo",
        limit=10,
    )

    assert errors == []
    assert len(items) == 1
    assert items[0].title == "Bug in source pipeline"
    assert items[0].tags == ["issue", "bug"]
    assert items[0].metadata["github_surface"] == "issues"


def test_github_connector_fetches_pull_requests() -> None:
    items, errors = GithubConnector(fetch_text=lambda url: GITHUB_PULLS).fetch_pull_requests(
        _source(),
        repository="owner/repo",
        limit=1,
    )

    assert errors == []
    assert items[0].title == "Improve connector"
    assert items[0].tags == ["pull_request", "enhancement"]
    assert items[0].metadata["github_surface"] == "pull_requests"


def test_github_connector_fetches_security_advisories() -> None:
    captured = {}

    def fetch_text(url: str) -> str:
        captured["url"] = url
        return GITHUB_ADVISORIES

    items, errors = GithubConnector(fetch_text=fetch_text).fetch_security_advisories(
        _source(),
        repository="owner/repo",
        limit=1,
    )

    assert errors == []
    assert captured["url"] == f"{GITHUB_API_URL}/advisories?affects=owner%2Frepo&per_page=1"
    assert items[0].title == "Critical package issue"
    assert items[0].tags == ["security_advisory", "critical"]
    assert items[0].metadata["ghsa_id"] == "GHSA-xxxx-yyyy"


def test_github_connector_fetches_repository_search_items_for_trending_mode() -> None:
    source = SourceDefinition(
        source_id="github-trending",
        name="GitHub Trending",
        source_type="github",
        url=GITHUB_API_URL,
        reliability="medium",
        metadata={"mode": "trending", "query": "topic:ai"},
    )
    captured = {}

    def fetch_text(url: str) -> str:
        captured["url"] = url
        return GITHUB_SEARCH

    items, errors = GithubConnector(fetch_text=fetch_text).fetch(source, limit=1)

    assert errors == []
    assert "search/repositories" in captured["url"]
    assert "sort=stars" in captured["url"]
    assert items[0].title == "owner/repo"
    assert items[0].metadata["github_surface"] == "repository_search"
    assert items[0].metadata["stargazers_count"] == 123


def test_github_connector_fetches_discussions_with_graphql_fetcher() -> None:
    captured = {}
    source = SourceDefinition(
        source_id="github-discussions",
        name="GitHub Discussions",
        source_type="github",
        url=GITHUB_API_URL,
        reliability="high",
        metadata={"mode": "discussions", "repository": "owner/repo"},
    )

    def fetch_graphql(url: str, payload: dict) -> str:
        captured["url"] = url
        captured["variables"] = payload["variables"]
        return GITHUB_DISCUSSIONS

    items, errors = GithubConnector(fetch_graphql=fetch_graphql).fetch(source, limit=1)

    assert errors == []
    assert captured["url"] == f"{GITHUB_API_URL}/graphql"
    assert captured["variables"] == {"owner": "owner", "name": "repo", "first": 1}
    assert items[0].title == "Runtime architecture discussion"
    assert items[0].url == "https://github.com/owner/repo/discussions/12"
    assert items[0].authors == ["maintainer"]
    assert items[0].tags == ["discussion", "Ideas"]
    assert items[0].metadata["github_surface"] == "discussions"
    assert items[0].metadata["comment_count"] == 3


def test_github_discussions_default_fetch_requires_auth_token(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    source = SourceDefinition(
        source_id="github-discussions",
        name="GitHub Discussions",
        source_type="github",
        url=GITHUB_API_URL,
        reliability="high",
        metadata={"mode": "discussions", "repository": "owner/repo"},
    )

    items, errors = GithubConnector().fetch(source, limit=1)

    assert items == []
    assert errors[0].error_type == "invalid_source_config"
    assert errors[0].metadata["operator_action_required"] is True


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

    monkeypatch.setattr("infrastructure.external.sources.github.open_request_with_fetch_policy", fake_open_request)

    items, errors = GithubConnector().fetch_releases(
        _source(respect_robots=False),
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


def _source(*, respect_robots: bool = True) -> SourceDefinition:
    return SourceDefinition(
        source_id="github",
        name="GitHub",
        source_type="github",
        url=GITHUB_API_URL,
        reliability="high",
        authority_score=0.9,
        language="en",
        respect_robots=respect_robots,
    )
