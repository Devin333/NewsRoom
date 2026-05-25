import json
from datetime import datetime, timezone

from interfaces.services.paper_service import PaperListQuery, PapersApplicationService


def test_paper_service_filters_sorts_and_preserves_real_only_fields(tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    cache_path.write_text(
        json.dumps(
            {
                "papers": [
                    {
                        "id": "paper-fresh",
                        "title": "Fresh Agent Paper",
                        "abstractSnippet": "Fresh agent paper with code.",
                        "authors": ["A"],
                        "publishedAt": "2026-05-24T00:00:00Z",
                        "citationCount": 3,
                        "githubStars": 16,
                        "taskRefs": [{"id": "task-agents", "slug": "agents", "name": "Agents"}],
                        "methodRefs": [{"id": "method-react", "slug": "react", "name": "ReAct"}],
                        "paperUrl": "https://arxiv.org/abs/2605.1",
                        "repoUrl": "https://github.com/owner/fresh",
                    },
                    {
                        "id": "paper-old",
                        "title": "Old Agent Paper",
                        "abstractSnippet": "Old agent paper.",
                        "authors": ["B"],
                        "publishedAt": "2025-01-01T00:00:00Z",
                        "citationCount": 100,
                        "taskRefs": [{"id": "task-agents", "slug": "agents", "name": "Agents"}],
                        "methodRefs": [{"id": "method-react", "slug": "react", "name": "ReAct"}],
                        "paperUrl": "https://arxiv.org/abs/2501.1",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    service = PapersApplicationService(
        papers_data_path=cache_path,
        clock=lambda: datetime(2026, 5, 25, tzinfo=timezone.utc),
    )

    result = service.list_papers(PaperListQuery(q="agent", period="weekly", sort="most_cited", task="agents", method="react"))
    paper = result.papers[0]

    assert result.total_count == 1
    assert paper.id == "paper-fresh"
    assert paper.implementations[0].repoUrl == "https://github.com/owner/fresh"
    assert paper.benchmarks == ()
    assert paper.newsroomHeatScore is not None


def test_paper_service_summary_cache_uses_locale_and_abstract_hash(tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    summary_path = tmp_path / "summaries.json"
    cache_path.write_text(
        json.dumps(
            {
                "papers": [
                    {
                        "id": "paper-summary",
                        "title": "Summary Paper",
                        "abstractSnippet": "Abstract text.",
                        "authors": ["A"],
                        "publishedAt": "2026-05-24T00:00:00Z",
                        "paperUrl": "https://arxiv.org/abs/2605.2",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    class FakeClient:
        calls = 0

        def complete(self, request):
            FakeClient.calls += 1

            class Response:
                content = '{"summary":"真实摘要","keyInsights":["A"],"limitations":[]}'

            return Response()

    service = PapersApplicationService(
        papers_data_path=cache_path,
        summary_cache_path=summary_path,
        llm_client_factory=lambda route: FakeClient(),
        clock=lambda: datetime(2026, 5, 25, tzinfo=timezone.utc),
    )

    first = service.get_or_generate_summary("paper-summary", locale="zh")
    second = service.get_or_generate_summary("paper-summary", locale="zh")

    assert first.summary == "真实摘要"
    assert first.cached is False
    assert second.cached is True
    assert FakeClient.calls == 1
