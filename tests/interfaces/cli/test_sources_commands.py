import json
from types import SimpleNamespace

import interfaces.cli.news as news_cli
from interfaces.cli.commands import sources as source_commands


def test_news_cli_sources_list_json(monkeypatch, capsys) -> None:
    _patch_source_service(monkeypatch)

    exit_code = news_cli.main(["sources", "list", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["source_count"] == 1
    assert payload["sources"][0]["source_id"] == "source-1"


def test_news_cli_sources_health_json(monkeypatch, capsys) -> None:
    _patch_source_service(monkeypatch)

    exit_code = news_cli.main(["sources", "health", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["health"][0]["status"] == "healthy"


def test_news_cli_sources_check_health_json(monkeypatch, capsys) -> None:
    _patch_source_service(monkeypatch)

    exit_code = news_cli.main(
        ["sources", "check-health", "--source-id", "source-1", "--limit", "1", "--json"]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["checked_count"] == 1
    assert payload["entries"][0]["source_id"] == "source-1"


def test_news_cli_sources_validate_json(monkeypatch, capsys) -> None:
    _patch_source_service(monkeypatch)

    exit_code = news_cli.main(["sources", "validate", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["is_valid"] is True
    assert payload["error_count"] == 0


def test_news_cli_sources_arxiv_json(monkeypatch, capsys) -> None:
    _patch_source_service(monkeypatch)

    exit_code = news_cli.main(["sources", "arxiv", "--query", "cat:cs.AI", "--limit", "1", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["source_type"] == "arxiv"
    assert payload["item_count"] == 1
    assert payload["items"][0]["title"] == "Agent Runtime Evaluation"


def test_news_cli_sources_github_json(monkeypatch, capsys) -> None:
    _patch_source_service(monkeypatch)

    exit_code = news_cli.main(["sources", "github", "--repo", "owner/repo", "--limit", "1", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["source_type"] == "github"
    assert payload["item_count"] == 1
    assert payload["items"][0]["title"] == "Version 1.0.0"


class _FakeSourceService:
    def list_sources(self, *, enabled_only):
        return _FakeResult(
            {
                "source_count": 1,
                "sources": [
                    {
                        "source_id": "source-1",
                        "name": "Source",
                        "source_type": "rss",
                        "url": "https://example.com/rss",
                        "reliability": "high",
                        "authority_score": 0.9,
                        "enabled": True,
                        "topics": ["AI"],
                        "language": None,
                        "region": None,
                    }
                ],
            }
        )

    def source_health(self, *, enabled_only):
        return _FakeResult(
            {
                "source_count": 1,
                "health": [
                    {
                        "source_id": "source-1",
                        "status": "healthy",
                        "consecutive_failures": 0,
                        "last_success_at": None,
                        "last_failure_at": None,
                        "cooldown_until": None,
                        "last_error": None,
                    }
                ],
            }
        )

    def validate_sources(self):
        return _FakeResult(
            {
                "is_valid": True,
                "error_count": 0,
                "warning_count": 0,
                "issues": [],
            }
        )

    def check_source_health(self, *, source_id, enabled_only, limit, force):
        return _FakeResult(
            {
                "checked_count": 1,
                "succeeded_count": 1,
                "failed_count": 0,
                "skipped_count": 0,
                "entries": [{"source_id": source_id, "ok": True, "status": "healthy"}],
                "events": [],
            }
        )

    def fetch_arxiv(self, *, query, limit):
        return _FakeResult(
            {
                "source_id": "arxiv",
                "source_type": "arxiv",
                "query": query,
                "item_count": 1,
                "error_count": 0,
                "items": [
                    {
                        "source_item_id": "raw-arxiv",
                        "source_id": "arxiv",
                        "source_name": "arXiv",
                        "source_type": "arxiv",
                        "title": "Agent Runtime Evaluation",
                        "url": "https://arxiv.org/abs/2605.00001",
                        "fetched_at": "2026-05-11T00:00:00Z",
                        "published_at": "2026-05-10T00:00:00Z",
                        "summary": "Paper summary",
                        "raw_content": None,
                        "authors": ["Alice Example"],
                        "tags": ["cs.AI"],
                        "language": "en",
                        "metadata": {"arxiv_id": "2605.00001v1"},
                    }
                ],
                "errors": [],
            }
        )

    def fetch_github_releases(self, *, repository, limit):
        return _FakeResult(
            {
                "source_id": "github",
                "source_type": "github",
                "query": repository,
                "item_count": 1,
                "error_count": 0,
                "items": [
                    {
                        "source_item_id": "raw-github",
                        "source_id": "github",
                        "source_name": "GitHub",
                        "source_type": "github",
                        "title": "Version 1.0.0",
                        "url": "https://github.com/owner/repo/releases/tag/v1.0.0",
                        "fetched_at": "2026-05-11T00:00:00Z",
                        "published_at": "2026-05-10T00:00:00Z",
                        "summary": "Release notes",
                        "raw_content": None,
                        "authors": ["maintainer"],
                        "tags": ["v1.0.0"],
                        "language": "en",
                        "metadata": {"repository": "owner/repo"},
                    }
                ],
                "errors": [],
            }
        )


class _FakeResult:
    def __init__(self, payload) -> None:
        self.payload = payload

    def to_dict(self):
        return self.payload


def _patch_source_service(monkeypatch) -> None:
    monkeypatch.setattr(
        source_commands,
        "build_source_runtime_composition",
        lambda: SimpleNamespace(source_service=_FakeSourceService()),
    )
