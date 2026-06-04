import json
from datetime import datetime, timezone

import pytest

from interfaces.services.paper_service import (
    PAPER_SUMMARY_SCHEMA_VERSION,
    PaperListQuery,
    PaperSummaryUnavailableError,
    PapersApplicationService,
    _summary_from_payload,
    legacy_summary_cache_key,
    summary_cache_key,
)


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


def test_paper_service_summary_v2_uses_public_context_and_separate_cache(tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    summary_path = tmp_path / "summaries.json"
    paper_payload = {
        "id": "paper-summary-v2",
        "title": "Structured Summary Paper",
        "abstractSnippet": "The paper introduces a grounded reader system for agent papers.",
        "authors": ["A"],
        "publishedAt": "2026-05-24T00:00:00Z",
        "paperUrl": "https://arxiv.org/abs/2605.20001",
        "taskRefs": [{"id": "task-agents", "slug": "agents", "name": "Agents", "group": "agents"}],
        "methodRefs": [{"id": "method-rag", "slug": "rag", "name": "Retrieval Augmented Generation", "area": "Language Models"}],
        "repoUrl": "https://github.com/owner/summary-v2",
        "githubStars": 128,
        "benchmarks": [{"id": "bench-mmlu", "name": "MMLU", "category": "language-understanding", "metric": "accuracy", "value": "91.2"}],
        "evidenceRefs": [
            {
                "evidenceId": "ev-1",
                "title": "Public evidence",
                "summary": "Public evidence summary.",
                "raw_payload": {"token": "secret"},
                "authorization": "Bearer secret",
            }
        ],
    }
    cache_path.write_text(json.dumps({"papers": [paper_payload]}), encoding="utf-8")

    class FakeClient:
        calls = 0
        prompts: list[str] = []

        def complete(self, request):
            FakeClient.calls += 1
            FakeClient.prompts.append(request.estimated_prompt_text())

            class Response:
                content = json.dumps(
                    {
                        "summary": "A structured summary grounded in public signals.",
                        "keyInsights": ["The reader system uses retrieved evidence."],
                        "limitations": ["No private PDF text is used."],
                        "contributions": ["Adds structured reader summaries."],
                        "methodSummary": "Uses Retrieval Augmented Generation over public sections.",
                        "experimentSummary": "Reports MMLU accuracy as a public benchmark signal.",
                        "engineeringRelevance": "Useful for teams comparing agent paper implementations.",
                        "readingDifficulty": "medium",
                        "recommendedAudience": ["engineer", "researcher"],
                        "raw_payload": {"token": "secret"},
                    }
                )

            return Response()

    service = PapersApplicationService(
        papers_data_path=cache_path,
        summary_cache_path=summary_path,
        llm_client_factory=lambda route: FakeClient(),
        clock=lambda: datetime(2026, 5, 25, tzinfo=timezone.utc),
    )
    paper = service.get_paper("paper-summary-v2")
    legacy_key = legacy_summary_cache_key(paper, locale="en", route=service._summary_route())
    summary_path.write_text(
        json.dumps(
            {
                legacy_key: {
                    "paperId": "paper-summary-v2",
                    "locale": "en",
                    "modelRoute": service._summary_route(),
                    "abstractHash": "legacy",
                    "summary": "Legacy summary should not be reused as v2.",
                    "keyInsights": [],
                    "limitations": [],
                    "generatedAt": "2026-05-24T00:00:00Z",
                }
            }
        ),
        encoding="utf-8",
    )

    first = service.get_or_generate_summary("paper-summary-v2", locale="en")
    second = service.get_or_generate_summary("paper-summary-v2", locale="en")

    assert first.summary == "A structured summary grounded in public signals."
    assert first.contributions == ("Adds structured reader summaries.",)
    assert first.methodSummary == "Uses Retrieval Augmented Generation over public sections."
    assert first.experimentSummary == "Reports MMLU accuracy as a public benchmark signal."
    assert first.engineeringRelevance == "Useful for teams comparing agent paper implementations."
    assert first.readingDifficulty == "medium"
    assert first.recommendedAudience == ("engineer", "researcher")
    assert first.summarySchemaVersion == PAPER_SUMMARY_SCHEMA_VERSION
    assert second.cached is True
    assert FakeClient.calls == 1

    prompt = FakeClient.prompts[0]
    assert "Retrieval Augmented Generation" in prompt
    assert "Language Models" in prompt
    assert "MMLU" in prompt
    assert "language-understanding" in prompt
    assert "github.com/owner/summary-v2" in prompt
    assert "Public evidence summary" in prompt
    assert "raw_payload" not in prompt
    assert "authorization" not in prompt
    assert "token" not in prompt
    assert "secret" not in prompt

    cache_payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert legacy_key in cache_payload
    assert summary_cache_key(paper, locale="en", route=service._summary_route()) in cache_payload
    serialized = json.dumps(cache_payload)
    assert "raw_payload" not in serialized
    assert "token" not in serialized
    assert "secret" not in serialized


def test_paper_summary_parser_keeps_legacy_compatibility_and_drops_invalid_difficulty() -> None:
    legacy = _summary_from_payload(
        {
            "paperId": "legacy-paper",
            "locale": "en",
            "modelRoute": "writer-primary",
            "abstractHash": "abc",
            "summary": "Legacy summary.",
            "keyInsights": ["A"],
            "limitations": [],
            "readingDifficulty": "expert",
            "raw_content": "secret",
        }
    )

    assert legacy is not None
    assert legacy.summary == "Legacy summary."
    assert legacy.summarySchemaVersion is None
    assert legacy.readingDifficulty is None
    serialized = json.dumps(legacy.to_dict())
    assert "raw_content" not in serialized
    assert "secret" not in serialized


def test_paper_reader_ops_stats_aggregate_summary_events_and_runtime_files(tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    summary_path = tmp_path / "summaries.json"
    events_path = tmp_path / "summary-events.jsonl"
    reader_cache_dir = tmp_path / "reader-cache"
    text_extraction_dir = tmp_path / "text-extractions"
    cache_path.write_text(
        json.dumps(
            {
                "source": "unit-cache",
                "collectedAt": "2026-05-24T12:00:00Z",
                "papers": [
                    {
                        "id": "ops-paper",
                        "slug": "ops-paper",
                        "title": "Ops Paper",
                        "abstractSnippet": "A paper for operations stats.",
                        "authors": ["A"],
                        "publishedAt": "2026-05-24T00:00:00Z",
                        "paperUrl": "https://arxiv.org/abs/2605.30001",
                        "isPublished": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    class FakeClient:
        calls = 0

        def complete(self, request):
            FakeClient.calls += 1

            class Response:
                content = json.dumps(
                    {
                        "summary": "Summary from public metadata.",
                        "keyInsights": ["Public signal"],
                        "limitations": [],
                        "raw_payload": {"token": "secret"},
                    }
                )

            return Response()

    service = PapersApplicationService(
        papers_data_path=cache_path,
        summary_cache_path=summary_path,
        summary_events_path=events_path,
        reader_cache_dir=reader_cache_dir,
        text_extraction_dir=text_extraction_dir,
        llm_client_factory=lambda route: FakeClient(),
        clock=lambda: datetime(2026, 5, 25, tzinfo=timezone.utc),
    )
    service.get_or_generate_summary("ops-paper", locale="en")
    cached = service.get_or_generate_summary("ops-paper", locale="en")
    service.get_reader_payload("ops-paper", locale="en")
    text_extraction_dir.mkdir(exist_ok=True)
    (text_extraction_dir / "ops-paper.json").write_text(
        json.dumps({"paperId": "ops-paper", "sourceHash": "stale", "sections": []}),
        encoding="utf-8",
    )

    stats = service.get_ops_stats(window_hours=24)

    assert cached.cached is True
    assert stats["dataState"] == "ready"
    assert stats["paperCache"]["paperCount"] == 1
    assert stats["paperCache"]["collectedAt"] == "2026-05-24T12:00:00Z"
    assert stats["summaryCache"]["entryCount"] == 1
    assert stats["summaryCache"]["v2EntryCount"] == 1
    assert stats["summaryEvents"]["eventCount"] == 2
    assert stats["summaryEvents"]["generatedCount"] == 1
    assert stats["summaryEvents"]["cacheHitCount"] == 1
    assert stats["summaryEvents"]["hitRate"] == 0.5
    assert stats["readerCache"]["fileCount"] == 1
    assert stats["textExtraction"]["fileCount"] == 1
    serialized_events = events_path.read_text(encoding="utf-8")
    assert "raw_payload" not in serialized_events
    assert "token" not in serialized_events
    assert "secret" not in serialized_events


def test_paper_reader_ops_stats_empty_partial_and_failed_summary_events(tmp_path) -> None:
    empty_service = PapersApplicationService(
        papers_data_path=tmp_path / "missing-papers.json",
        summary_cache_path=tmp_path / "missing-summaries.json",
        summary_events_path=tmp_path / "missing-events.jsonl",
        reader_cache_dir=tmp_path / "missing-reader-cache",
        text_extraction_dir=tmp_path / "missing-text-extractions",
        clock=lambda: datetime(2026, 5, 25, tzinfo=timezone.utc),
    )
    empty_stats = empty_service.get_ops_stats()
    assert empty_stats["dataState"] == "empty"
    assert empty_stats["summaryEvents"]["eventCount"] == 0

    cache_path = tmp_path / "papers.json"
    summary_path = tmp_path / "corrupt-summaries.json"
    events_path = tmp_path / "summary-events.jsonl"
    cache_path.write_text(
        json.dumps(
            {
                "papers": [
                    {
                        "id": "failure-paper",
                        "title": "Failure Paper",
                        "abstractSnippet": "A paper for failure stats.",
                        "authors": ["A"],
                        "publishedAt": "2026-05-24T00:00:00Z",
                        "paperUrl": "https://arxiv.org/abs/2605.30002",
                        "isPublished": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    summary_path.write_text("{not-json", encoding="utf-8")
    events_path.write_text("{not-json\n", encoding="utf-8")

    class FailingClient:
        def complete(self, request):
            raise RuntimeError("provider token secret should not leak")

    service = PapersApplicationService(
        papers_data_path=cache_path,
        summary_cache_path=summary_path,
        summary_events_path=events_path,
        reader_cache_dir=tmp_path / "reader-cache",
        text_extraction_dir=tmp_path / "text-extractions",
        llm_client_factory=lambda route: FailingClient(),
        clock=lambda: datetime(2026, 5, 25, tzinfo=timezone.utc),
    )

    summary = service.get_or_generate_summary("failure-paper", locale="en")

    assert summary.summary.startswith("Failure Paper is a research paper")
    assert summary.cached is False
    assert summary.summarySchemaVersion == PAPER_SUMMARY_SCHEMA_VERSION

    stats = service.get_ops_stats()
    assert stats["dataState"] == "partial"
    assert stats["summaryCache"]["status"] == "ready"
    assert stats["summaryCache"]["entryCount"] == 1
    assert stats["summaryEvents"]["status"] == "partial"
    assert stats["summaryEvents"]["failureCount"] == 0
    assert stats["summaryEvents"]["fallbackGeneratedCount"] == 1
    assert stats["summaryEvents"]["errorCodeCounts"]["paper_summary_fallback:PaperSummaryUnavailableError"] == 1
    assert "secret" not in json.dumps(stats)


def test_paper_summary_refresh_bypasses_v2_cache_and_overwrites_current_entry(tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    summary_path = tmp_path / "summaries.json"
    events_path = tmp_path / "events.jsonl"
    cache_path.write_text(
        json.dumps(
            {
                "papers": [
                    {
                        "id": "refresh-paper",
                        "title": "Refresh Paper",
                        "abstractSnippet": "A paper for refresh.",
                        "authors": ["A"],
                        "publishedAt": "2026-05-24T00:00:00Z",
                        "paperUrl": "https://arxiv.org/abs/2605.30003",
                        "isPublished": True,
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
                content = json.dumps({"summary": f"Generated summary {FakeClient.calls}", "keyInsights": [], "limitations": []})

            return Response()

    service = PapersApplicationService(
        papers_data_path=cache_path,
        summary_cache_path=summary_path,
        summary_events_path=events_path,
        llm_client_factory=lambda route: FakeClient(),
        clock=lambda: datetime(2026, 5, 25, tzinfo=timezone.utc),
    )

    first = service.get_or_generate_summary("refresh-paper", locale="en")
    cached = service.get_or_generate_summary("refresh-paper", locale="en")
    refreshed = service.get_or_generate_summary("refresh-paper", locale="en", refresh=True)
    cached_after_refresh = service.get_or_generate_summary("refresh-paper", locale="en")

    assert first.summary == "Generated summary 1"
    assert cached.summary == "Generated summary 1"
    assert cached.cached is True
    assert refreshed.summary == "Generated summary 2"
    assert refreshed.cached is False
    assert cached_after_refresh.summary == "Generated summary 2"
    assert cached_after_refresh.cached is True
    assert FakeClient.calls == 2
