import json
from types import SimpleNamespace

import interfaces.cli.news as news_cli


def test_news_cli_sources_fetch_json(monkeypatch, capsys) -> None:
    _patch_source_service(monkeypatch)

    exit_code = news_cli.main(["sources", "fetch", "--source-id", "source-1", "--limit", "2", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["source_id"] == "source-1"
    assert payload["item_count"] == 1


def test_news_cli_sources_fetch_category_json(monkeypatch, capsys) -> None:
    _patch_source_service(monkeypatch)

    exit_code = news_cli.main(
        ["sources", "fetch-category", "--category", "research", "--limit-per-source", "1", "--json"]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["source_count"] == 1
    assert payload["ok"] is True


def test_news_cli_sources_fetch_priority_json(monkeypatch, capsys) -> None:
    _patch_source_service(monkeypatch)

    exit_code = news_cli.main(
        ["sources", "fetch-priority", "--priority", "p0", "--limit-per-source", "1", "--json"]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["source_count"] == 1


def test_news_cli_sources_fetch_topic_json(monkeypatch, capsys) -> None:
    _patch_source_service(monkeypatch)

    exit_code = news_cli.main(
        ["sources", "fetch-topic", "--topic", "AI agents", "--limit-per-source", "1", "--json"]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["selection_report"]["topic"] == "AI agents"


def test_news_cli_sources_inspect_json(monkeypatch, capsys) -> None:
    _patch_source_service(monkeypatch)

    exit_code = news_cli.main(["sources", "inspect", "--source-id", "source-1", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["source_id"] == "source-1"


def test_sources_command_reuses_one_runtime_provider_for_consecutive_handlers(
    monkeypatch,
    capsys,
) -> None:
    _patch_source_service(monkeypatch)
    parser = news_cli.build_parser()
    args = parser.parse_args(
        ["sources", "fetch", "--source-id", "source-1", "--json"]
    )

    first = args.handler(args)
    second = args.handler(args)

    assert first == 0
    assert second == 0
    assert capsys.readouterr().out.count('"source_id": "source-1"') == 2


def test_news_cli_sources_categories_and_priorities_json(monkeypatch, capsys) -> None:
    _patch_source_service(monkeypatch)

    categories_code = news_cli.main(["sources", "categories", "--json"])
    categories = json.loads(capsys.readouterr().out)
    priorities_code = news_cli.main(["sources", "priorities", "--json"])
    priorities = json.loads(capsys.readouterr().out)

    assert categories_code == 0
    assert categories["categories"] == ["research"]
    assert priorities_code == 0
    assert priorities["priorities"] == ["p0"]


class _FakeSourceService:
    def get_source(self, source_id):
        return _FakeResult(
            {
                "source_id": source_id,
                "source": {
                    "source_id": source_id,
                    "name": "Source",
                    "source_type": "rss",
                    "url": "https://example.com/rss.xml",
                    "reliability": "high",
                    "authority_score": 0.9,
                    "enabled": True,
                    "respect_robots": True,
                    "fetch_interval_seconds": 3600,
                    "topics": ["ai"],
                    "category": "research",
                    "language": "en",
                    "region": "global",
                    "user_agent": None,
                },
            }
        )

    def fetch_source(self, *, source_id, limit, query=None, force=False):
        return _FakeResult(_fetch_payload(source_id=source_id))

    def fetch_category(
        self,
        *,
        category,
        limit_per_source,
        enabled_only=True,
        priority=None,
        language=None,
        region=None,
        force=False,
    ):
        return _FakeResult(_batch_payload())

    def fetch_priority(self, *, priority, limit_per_source, enabled_only=True, force=False):
        return _FakeResult(_batch_payload())

    def fetch_topic_sources(
        self,
        *,
        topic,
        limit_per_source,
        enabled_only=True,
        category=None,
        priority=None,
        language=None,
        region=None,
        force=False,
    ):
        payload = _batch_payload()
        payload["selection_report"] = {"topic": topic, "selected_source_ids": ["source-1"]}
        return _FakeResult(payload)

    def source_categories(self):
        return {"categories": ["research"], "category_count": 1}

    def source_priorities(self):
        return {"priorities": ["p0"], "priority_count": 1}


def _fetch_payload(*, source_id: str):
    return {
        "source_id": source_id,
        "source_type": "rss",
        "query": "",
        "item_count": 1,
        "error_count": 0,
        "items": [{"title": "Fetched item", "url": "https://example.com/item"}],
        "errors": [],
    }


def _batch_payload():
    return {
        "ok": True,
        "source_count": 1,
        "item_count": 1,
        "error_count": 0,
        "skipped_count": 0,
        "results": [_fetch_payload(source_id="source-1")],
        "selection_report": None,
    }


class _FakeResult:
    def __init__(self, payload) -> None:
        self.payload = payload

    def to_dict(self):
        return self.payload


def _patch_source_service(monkeypatch) -> None:
    monkeypatch.setattr(
        news_cli,
        "build_source_runtime_provider",
        lambda: _FakeSourceRuntimeProvider(),
    )


class _FakeSourceRuntimeProvider:
    def __init__(self) -> None:
        self._composition = SimpleNamespace(source_service=_FakeSourceService())

    def get(self):
        return self._composition
