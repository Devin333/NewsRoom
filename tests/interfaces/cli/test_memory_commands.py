import json

import interfaces.cli.news as news_cli


def test_news_cli_memory_search_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "MemoryApplicationService", _FakeMemoryService)

    exit_code = news_cli.main(
        [
            "memory",
            "search",
            "agent runtime",
            "--collection",
            "report_sections",
            "--limit",
            "2",
            "--filter",
            "topic=AI",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["collection"] == "report_sections"
    assert payload["query"] == "agent runtime"
    assert payload["filters"] == {"topic": "AI"}
    assert payload["results"][0]["document_id"] == "doc-1"


def test_news_cli_memory_reindex_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "MemoryApplicationService", _FakeMemoryService)

    exit_code = news_cli.main(
        [
            "memory",
            "reindex",
            "--run-id",
            "run-1",
            "--topic",
            "AI policy",
            "--artifact-root",
            ".newsroom/test-runs",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["run_id"] == "run-1"
    assert payload["topic"] == "AI policy"
    assert payload["documents_indexed"] == 3
    assert payload["collections"] == ["evidence_items", "report_sections"]


def test_news_cli_memory_reindex_missing_run_returns_error(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "MemoryApplicationService", _FakeMemoryService)

    exit_code = news_cli.main(["memory", "reindex", "--run-id", "missing", "--json"])

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "run not found" in captured.out


class _FakeMemoryService:
    def __init__(self, artifact_root=".newsroom/runs") -> None:
        self.artifact_root = artifact_root

    def search(self, **kwargs):
        return _FakeMemoryResult(
            {
                "collection": kwargs["collection"],
                "query": kwargs["text"],
                "filters": kwargs["filters"],
                "limit": kwargs["limit"],
                "result_count": 1,
                "results": [
                    {
                        "document_id": "doc-1",
                        "score": 0.9,
                        "text": "Agent runtime memory",
                        "source_type": "report_section",
                        "payload": {"topic": "AI"},
                        "run_id": None,
                        "report_id": None,
                        "evidence_id": None,
                        "source_item_id": None,
                    }
                ],
            }
        )

    def reindex_run(self, run_id, *, topic=None):
        if run_id == "missing":
            raise FileNotFoundError("run not found: missing")
        return _FakeMemoryResult(
            {
                "run_id": run_id,
                "topic": topic,
                "documents_indexed": 3,
                "collections": ["evidence_items", "report_sections"],
                "document_ids": ["run-1:report_section:0", "run-1:report_section:1", "run-1:evidence:ev-1"],
            }
        )


class _FakeMemoryResult:
    def __init__(self, payload) -> None:
        self.payload = payload

    def to_dict(self):
        return self.payload
