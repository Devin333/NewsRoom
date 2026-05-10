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


class _FakeMemoryService:
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


class _FakeMemoryResult:
    def __init__(self, payload) -> None:
        self.payload = payload

    def to_dict(self):
        return self.payload
