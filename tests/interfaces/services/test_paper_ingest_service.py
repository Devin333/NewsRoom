import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from framework.llm import LLMConfigurationError
from infrastructure.external.sources.github import GithubRepositoryMetadata
from infrastructure.external.sources.models import RawSourceItem, SourceError
from interfaces.services.paper_ingest_service import (
    PaperCitationMetadata,
    PaperIngestApplicationService,
    PaperIngestConfig,
    PaperPdfExtraction,
)
from business.boards.paper_radar.agents import PaperAnalysisResult
from interfaces.services.paper_reader_cache_repository import TextExtractionRepository
from interfaces.services.paper_taxonomy_categories import (
    BENCHMARK_CATEGORIES,
    load_pwc_method_collections,
    normalize_benchmark_category,
    normalize_method_collection,
)


def test_paper_taxonomy_loads_pwc_method_collections_and_benchmark_categories() -> None:
    collections = load_pwc_method_collections()

    assert "Transformers" in collections
    assert normalize_method_collection("transformers") == "Transformers"
    assert len(BENCHMARK_CATEGORIES) == 40
    assert normalize_benchmark_category("question answering") == "question-answering"


def test_paper_ingest_publishes_github_arxiv_paper_with_thumbnail_and_taxonomy(tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    state_dir = tmp_path / "state"
    text_repo = TextExtractionRepository(tmp_path / "text")
    github = _FakeGithubConnector(stars=88)
    citation_client = _FakeCitationClient(
        {
            "10.48550/arxiv.2605.00001": PaperCitationMetadata(
                doi="10.48550/arxiv.2605.00001",
                citation_count=7,
                openalex_id="https://openalex.org/W260500001",
                display_name="Paper 2605.00001",
            )
        }
    )
    source = _FakeSourceService(
        [
            _candidate(
                "2605.00001",
                summary="Code is available at https://github.com/example/agent-paper.",
            )
        ]
    )

    service = PaperIngestApplicationService(
        source_service=source,
        github_connector=github,
        papers_data_path=cache_path,
        state_dir=state_dir,
        text_extraction_repository=text_repo,
        pdf_fetcher=lambda url, max_bytes: b"%PDF fake",
        pdf_processor=_FakePdfProcessor("The paper studies agent planning and reports MMLU 88."),
        citation_client=citation_client,
        llm_client_factory=lambda route: _FakeLLMClient(
            {
                "primaryTaskGroup": "agents",
                "secondaryTaskGroups": ["reasoning"],
                "taskRefs": [{"slug": "agent-planning", "name": "Agent Planning", "group": "agents", "confidence": 0.93, "evidence": "planning task"}],
                "methodRefs": [{"slug": "tree-search", "name": "Tree Search", "area": "Prompt Engineering", "confidence": 0.9, "evidence": "method section"}],
                "benchmarks": [{"name": "MMLU", "category": "question-answering", "metric": "accuracy", "value": "88", "taskSlug": "agent-planning", "confidence": 0.91}],
                "confidence": 0.92,
                "evidenceSummary": "The paper reports code, task, method, and benchmark evidence.",
            }
        ),
        config=PaperIngestConfig(candidate_limit=100, min_github_stars=50, auto_taxonomy_confidence=0.85),
        clock=_fixed_clock,
    )

    result = service.run_daily_ingest()

    assert source.calls == [("cat:cs.AI OR cat:cs.LG OR cat:cs.CL", 100)]
    assert github.calls[0]["respect_robots"] is False
    assert result.published_count == 1
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    paper = payload["papers"][0]
    assert paper["isPublished"] is True
    assert paper["repoUrl"] == "https://github.com/example/agent-paper"
    assert paper["githubStars"] == 88
    assert paper["citationDoi"] == "10.48550/arxiv.2605.00001"
    assert paper["citationCount"] == 7
    assert paper["openAlexId"] == "https://openalex.org/W260500001"
    assert citation_client.calls == [["10.48550/arxiv.2605.00001"]]
    assert paper["thumbnailUrl"].startswith("/api/papers/assets/thumbnails/")
    assert paper["taskRefs"][0]["slug"] == "agent-planning"
    assert paper["taskRefs"][0]["group"] == "agents"
    assert paper["methodRefs"][0]["slug"] == "tree-search"
    assert paper["methodRefs"][0]["area"] == "Prompt Engineering"
    assert paper["benchmarks"][0]["name"] == "MMLU"
    assert paper["benchmarks"][0]["category"] == "question-answering"
    assert paper["classification"]["primaryTaskGroup"] == "agents"
    assert paper["classification"]["confidence"] == 0.92
    assert (state_dir / "taxonomy-events.json").exists()
    assert text_repo.read_latest_sections("arxiv-2605.00001")


def test_paper_ingest_uses_agent_analysis_when_enabled(tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    orchestrator = _FakePaperAnalysisOrchestrator(
        {
            "primaryTaskGroup": "agents",
            "taskRefs": [{"id": "task-agents", "slug": "agents", "name": "Agents", "group": "agents", "confidence": 0.9}],
            "methodRefs": [{"id": "method-language-models", "slug": "language-models", "name": "Language Models", "area": "Language Models", "confidence": 0.9}],
            "benchmarks": [{"name": "SWE-bench", "category": "software-engineering", "metric": "resolved", "value": 32.4, "confidence": 0.9}],
            "confidence": 0.9,
            "evidenceSummary": "Agent analysis evidence.",
        }
    )
    llm_client = _FakeLLMClient(
        {
            "primaryTaskGroup": "code-ai",
            "taskRefs": [{"slug": "code-ai", "name": "Code AI", "group": "code-ai", "confidence": 0.9}],
            "methodRefs": [{"slug": "fallback", "name": "Fallback", "area": "Language Models", "confidence": 0.9}],
            "confidence": 0.9,
        }
    )
    service = _service(
        tmp_path,
        cache_path=cache_path,
        source_items=[_candidate("2605.01001", summary="Code is available at https://github.com/example/agent-analysis.")],
        pdf_text="The paper studies agent planning and reports SWE-bench 32.4% resolved.",
        llm_client=llm_client,
        paper_analysis_orchestrator=orchestrator,
        config=PaperIngestConfig(candidate_limit=100, min_github_stars=50, auto_taxonomy_confidence=0.85, use_agent_analysis=True),
    )

    result = service.run_daily_ingest(run_id="agent-analysis-run")

    paper = json.loads(cache_path.read_text(encoding="utf-8"))["papers"][0]
    assert result.published_count == 1
    assert orchestrator.requests[0].paper_id == "arxiv-2605.01001"
    assert orchestrator.requests[0].full_text is not None
    assert llm_client.calls == 0
    assert paper["taskRefs"][0]["slug"] == "agents"
    assert paper["classification"]["evidenceSummary"] == "Agent analysis evidence."


def test_paper_ingest_falls_back_when_agent_analysis_fails(tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    llm_client = _FakeLLMClient(
        {
            "primaryTaskGroup": "code-ai",
            "taskRefs": [{"slug": "code-ai", "name": "Code AI", "group": "code-ai", "confidence": 0.9}],
            "methodRefs": [{"slug": "fallback-method", "name": "Fallback Method", "area": "Language Models", "confidence": 0.9}],
            "confidence": 0.9,
            "evidenceSummary": "Fallback classifier evidence.",
        }
    )
    service = _service(
        tmp_path,
        cache_path=cache_path,
        source_items=[_candidate("2605.01002", summary="Code is available at https://github.com/example/fallback-analysis.")],
        llm_client=llm_client,
        paper_analysis_orchestrator=_FailingPaperAnalysisOrchestrator(),
        config=PaperIngestConfig(candidate_limit=100, min_github_stars=50, auto_taxonomy_confidence=0.85, use_agent_analysis=True),
    )

    result = service.run_daily_ingest(run_id="agent-fallback-run")

    paper = json.loads(cache_path.read_text(encoding="utf-8"))["papers"][0]
    assert result.published_count == 1
    assert llm_client.calls == 1
    assert paper["classification"]["evidenceSummary"] == "Fallback classifier evidence."
    assert any(item["repairAction"] == "fallback_to_legacy_classifier" for item in service.state.list_prompt_memory(limit=10))


def test_paper_ingest_extracts_explicit_github_from_pdf_text(tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    service = _service(
        tmp_path,
        cache_path=cache_path,
        source_items=[_candidate("2605.00002", summary="No repository in the abstract.")],
        pdf_text="Implementation: https://github.com/example/pdf-code.",
        stars=64,
        llm_payload={
            "primaryTaskGroup": "code-ai",
            "taskRefs": [{"slug": "code-generation", "name": "Code Generation", "group": "code-ai", "confidence": 0.9}],
            "methodRefs": [{"slug": "self-repair", "name": "Self Repair", "area": "Prompt Engineering", "confidence": 0.9}],
            "confidence": 0.9,
        },
    )

    result = service.run_daily_ingest()

    assert result.published_count == 1
    paper = json.loads(cache_path.read_text(encoding="utf-8"))["papers"][0]
    assert paper["repoUrl"] == "https://github.com/example/pdf-code"
    assert paper["taskRefs"][0]["group"] == "code-ai"


def test_paper_ingest_publishes_when_openalex_citation_is_temporarily_missing(tmp_path) -> None:
    service = _service(
        tmp_path,
        source_items=[_candidate("2605.00020", summary="Code: https://github.com/example/citation-soft-fail.")],
        stars=80,
        citation_client=_FakeCitationClient({}),
    )

    result = service.run_daily_ingest(run_id="citation-soft-fail")

    assert result.published_count == 1
    assert result.repair_queued_count == 1
    paper = json.loads((tmp_path / "papers.json").read_text(encoding="utf-8"))["papers"][0]
    assert paper["citationDoi"] == "10.48550/arxiv.2605.00020"
    assert paper["citationCount"] == 0
    repair = service.get_ops_state()["repairQueue"][0]
    assert repair["step"] == "citation_fetch"
    assert repair["errorCode"] == "openalex_citation_not_found"
    assert repair["context"]["nonBlocking"] is True


def test_paper_citation_backfill_updates_existing_published_papers(tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    cache_path.write_text(
        json.dumps(
            {
                "source": "test-cache",
                "papers": [
                    {
                        "id": "arxiv-2605.00021",
                        "title": "Citation Ready Paper",
                        "abstractSnippet": "A paper that needs OpenAlex citation enrichment.",
                        "paperUrl": "https://arxiv.org/abs/2605.00021",
                        "citationDoi": "10.48550/arxiv.2605.00021",
                        "citationCount": 0,
                        "isPublished": True,
                    },
                    {
                        "id": "already-synced",
                        "title": "Already Synced",
                        "abstractSnippet": "Skip me.",
                        "paperUrl": "https://arxiv.org/abs/2605.00022",
                        "citationDoi": "10.48550/arxiv.2605.00022",
                        "citationCount": 2,
                        "openAlexId": "https://openalex.org/W260500022",
                        "isPublished": True,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    citation_client = _FakeCitationClient(
        {
            "10.48550/arxiv.2605.00021": PaperCitationMetadata(
                doi="10.48550/arxiv.2605.00021",
                citation_count=12,
                openalex_id="https://openalex.org/W260500021",
                display_name="Citation Ready Paper",
            )
        }
    )
    service = PaperIngestApplicationService(
        source_service=_FakeSourceService([]),
        github_connector=_FakeGithubConnector(stars=120),
        papers_data_path=cache_path,
        state_dir=tmp_path / "state",
        citation_client=citation_client,
        config=PaperIngestConfig(candidate_limit=100),
        clock=_fixed_clock,
    )

    result = service.backfill_published_citations(run_id="citation-backfill-test", batch_size=1)

    assert result.scanned_count == 1
    assert result.updated_count == 1
    assert result.skipped_count == 1
    papers = json.loads(cache_path.read_text(encoding="utf-8"))["papers"]
    assert papers[0]["citationCount"] == 12
    assert papers[0]["openAlexId"] == "https://openalex.org/W260500021"
    assert papers[0]["citation"]["provider"] == "openalex"
    assert citation_client.calls == [["10.48550/arxiv.2605.00021"]]


def test_paper_citation_backfill_accepts_openalex_html_entities_in_title(tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    cache_path.write_text(
        json.dumps(
            {
                "source": "test-cache",
                "papers": [
                    {
                        "id": "arxiv-2605.00024",
                        "title": "Adaptive Attacks & Efficient Defenses",
                        "abstractSnippet": "A paper.",
                        "paperUrl": "https://arxiv.org/abs/2605.00024",
                        "citationDoi": "10.48550/arxiv.2605.00024",
                        "citationCount": 0,
                        "isPublished": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    service = PaperIngestApplicationService(
        source_service=_FakeSourceService([]),
        github_connector=_FakeGithubConnector(stars=120),
        papers_data_path=cache_path,
        state_dir=tmp_path / "state",
        citation_client=_FakeCitationClient(
            {
                "10.48550/arxiv.2605.00024": PaperCitationMetadata(
                    doi="10.48550/arxiv.2605.00024",
                    citation_count=3,
                    openalex_id="https://openalex.org/W260500024",
                    display_name="Adaptive Attacks &amp; Efficient Defenses",
                )
            }
        ),
        config=PaperIngestConfig(candidate_limit=100),
        clock=_fixed_clock,
    )

    result = service.backfill_published_citations(run_id="citation-html-title", batch_size=1)

    assert result.updated_count == 1
    assert result.repair_queued_count == 0
    paper = json.loads(cache_path.read_text(encoding="utf-8"))["papers"][0]
    assert paper["openAlexId"] == "https://openalex.org/W260500024"


def test_paper_citation_backfill_queues_repair_for_openalex_title_mismatch(tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    cache_path.write_text(
        json.dumps(
            {
                "source": "test-cache",
                "papers": [
                    {
                        "id": "arxiv-2605.00023",
                        "title": "Expected Paper Title",
                        "abstractSnippet": "A paper.",
                        "paperUrl": "https://arxiv.org/abs/2605.00023",
                        "citationDoi": "10.48550/arxiv.2605.00023",
                        "citationCount": 0,
                        "isPublished": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    service = PaperIngestApplicationService(
        source_service=_FakeSourceService([]),
        github_connector=_FakeGithubConnector(stars=120),
        papers_data_path=cache_path,
        state_dir=tmp_path / "state",
        citation_client=_FakeCitationClient(
            {
                "10.48550/arxiv.2605.00023": PaperCitationMetadata(
                    doi="10.48550/arxiv.2605.00023",
                    citation_count=5,
                    openalex_id="https://openalex.org/W260500023",
                    display_name="Different Work",
                )
            }
        ),
        config=PaperIngestConfig(candidate_limit=100),
        clock=_fixed_clock,
    )

    result = service.backfill_published_citations(run_id="citation-title-mismatch", batch_size=1)

    assert result.updated_count == 0
    assert result.repair_queued_count == 1
    paper = json.loads(cache_path.read_text(encoding="utf-8"))["papers"][0]
    assert "openAlexId" not in paper
    repair = service.get_ops_state()["repairQueue"][0]
    assert repair["errorCode"] == "openalex_title_mismatch"
    assert repair["repairAction"] == "normalize_doi_refetch_openalex_and_verify_title"


def test_paper_classification_backfill_updates_existing_published_papers(tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    cache_path.write_text(
        json.dumps(
            {
                "source": "test-cache",
                "papers": [
                    {
                        "id": "legacy-paper",
                        "title": "Legacy Agent Paper",
                        "abstractSnippet": "An agent paper with MMLU results.",
                        "authors": ["A"],
                        "publishedAt": "2026-05-20T00:00:00Z",
                        "paperUrl": "https://arxiv.org/abs/2605.00010",
                        "repoUrl": "https://github.com/example/legacy-agent",
                        "githubStars": 120,
                        "taskRefs": [{"id": "task-old", "slug": "old-agent", "name": "Old Agent"}],
                        "methodRefs": [{"id": "method-old", "slug": "old-method", "name": "Old Method"}],
                        "benchmarks": [{"id": "bench-mmlu", "name": "MMLU", "metric": "accuracy", "value": "88"}],
                        "isPublished": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    text_repo = TextExtractionRepository(tmp_path / "text")
    text_repo.write_sections(
        "legacy-paper",
        "source-hash",
        [{"title": "Experiments", "textExcerpt": "The agent system reports MMLU accuracy 88.", "sectionType": "experiment"}],
        cached_at="2026-05-27T08:00:00Z",
    )
    service = PaperIngestApplicationService(
        source_service=_FakeSourceService([]),
        github_connector=_FakeGithubConnector(stars=120),
        papers_data_path=cache_path,
        state_dir=tmp_path / "state",
        text_extraction_repository=text_repo,
        llm_client_factory=lambda route: _FakeLLMClient(
            {
                "primaryTaskGroup": "agents",
                "taskRefs": [{"slug": "agent-task-completion", "name": "Agent Task Completion", "group": "agents", "confidence": 0.91}],
                "methodRefs": [{"slug": "react", "name": "ReAct", "area": "Prompt Engineering", "confidence": 0.9}],
                "benchmarks": [{"name": "MMLU", "category": "language-understanding", "metric": "accuracy", "value": "88", "confidence": 0.9}],
                "confidence": 0.9,
            }
        ),
        config=PaperIngestConfig(candidate_limit=100, min_github_stars=50, auto_taxonomy_confidence=0.85),
        clock=_fixed_clock,
    )

    result = service.backfill_published_classification(run_id="backfill-test")

    assert result.updated_count == 1
    assert result.batch_size == 25
    paper = json.loads(cache_path.read_text(encoding="utf-8"))["papers"][0]
    assert paper["taskRefs"][0]["group"] == "agents"
    assert paper["methodRefs"][0]["area"] == "Prompt Engineering"
    assert paper["benchmarks"][0]["category"] == "language-understanding"
    assert paper["classification"]["schemaVersion"] == "paper_ingest_classification_v2"
    assert paper["classification"]["backfillTextSource"] == "text_extraction"
    assert paper["classification"]["fullTextAvailable"] is True


def test_paper_classification_backfill_extracts_pdf_when_text_cache_is_missing(tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    cache_path.write_text(
        json.dumps(
            {
                "source": "test-cache",
                "papers": [
                    {
                        "id": "arxiv-2605.00011",
                        "title": "PDF Only Agent Paper",
                        "abstractSnippet": "An agent paper with cached metadata only.",
                        "authors": ["A"],
                        "publishedAt": "2026-05-20T00:00:00Z",
                        "paperUrl": "https://arxiv.org/abs/2605.00011",
                        "pdfUrl": "https://arxiv.org/pdf/2605.00011",
                        "repoUrl": "https://github.com/example/pdf-agent",
                        "githubStars": 120,
                        "taskRefs": [{"slug": "legacy-task", "name": "Legacy Task"}],
                        "methodRefs": [{"slug": "legacy-method", "name": "Legacy Method"}],
                        "isPublished": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    text_repo = TextExtractionRepository(tmp_path / "text")
    service = PaperIngestApplicationService(
        source_service=_FakeSourceService([]),
        github_connector=_FakeGithubConnector(stars=120),
        papers_data_path=cache_path,
        state_dir=tmp_path / "state",
        text_extraction_repository=text_repo,
        pdf_fetcher=lambda url, max_bytes: b"%PDF fake",
        pdf_processor=_FakePdfProcessor("The full paper studies agent task completion and tool use."),
        llm_client_factory=lambda route: _FakeLLMClient(
            {
                "primaryTaskGroup": "agents",
                "taskRefs": [{"slug": "agent-task-completion", "name": "Agent Task Completion", "group": "agents", "confidence": 0.91}],
                "methodRefs": [{"slug": "tool-use", "name": "Tool Use", "area": "Prompt Engineering", "confidence": 0.9}],
                "confidence": 0.9,
            }
        ),
        config=PaperIngestConfig(candidate_limit=100, min_github_stars=50, auto_taxonomy_confidence=0.85),
        clock=_fixed_clock,
    )

    result = service.backfill_published_classification(run_id="backfill-pdf", batch_size=1)

    assert result.updated_count == 1
    assert text_repo.read_latest_sections("arxiv-2605.00011")
    paper = json.loads(cache_path.read_text(encoding="utf-8"))["papers"][0]
    assert paper["classification"]["backfillTextSource"] == "pdf_extract"
    assert paper["classification"]["fullTextAvailable"] is True
    assert paper["taskRefs"][0]["group"] == "agents"
    assert paper["methodRefs"][0]["area"] == "Prompt Engineering"


def test_paper_classification_backfill_uses_global_confidence_for_refs_without_item_confidence(tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    cache_path.write_text(
        json.dumps(
            {
                "source": "test-cache",
                "papers": [
                    {
                        "id": "paper-global-confidence",
                        "title": "Global Confidence Paper",
                        "abstractSnippet": "A paper with classifier-level confidence.",
                        "paperUrl": "https://arxiv.org/abs/2605.00016",
                        "repoUrl": "https://github.com/example/global-confidence",
                        "githubStars": 120,
                        "taskRefs": [{"slug": "legacy-task", "name": "Legacy Task"}],
                        "methodRefs": [{"slug": "legacy-method", "name": "Legacy Method"}],
                        "benchmarks": [{"name": "MMLU", "metric": "accuracy", "value": "88"}],
                        "isPublished": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    text_repo = TextExtractionRepository(tmp_path / "text")
    text_repo.write_sections(
        "paper-global-confidence",
        "source-hash",
        [{"title": "Body", "textExcerpt": "The paper reports MMLU accuracy.", "sectionType": "body"}],
        cached_at="2026-05-27T08:00:00Z",
    )
    service = PaperIngestApplicationService(
        source_service=_FakeSourceService([]),
        github_connector=_FakeGithubConnector(stars=120),
        papers_data_path=cache_path,
        state_dir=tmp_path / "state",
        text_extraction_repository=text_repo,
        llm_client_factory=lambda route: _FakeLLMClient(
            {
                "primaryTaskGroup": "language-models",
                "taskRefs": [{"slug": "language-understanding", "name": "Language Understanding", "group": "language-models"}],
                "methodRefs": [{"slug": "fine-tuning", "name": "Fine-Tuning"}],
                "benchmarks": [{"name": "MMLU", "category": "language-understanding", "metric": "accuracy", "value": "88"}],
                "confidence": 0.9,
            }
        ),
        config=PaperIngestConfig(candidate_limit=100, min_github_stars=50, auto_taxonomy_confidence=0.85),
        clock=_fixed_clock,
    )

    result = service.backfill_published_classification(run_id="backfill-global-confidence")

    assert result.updated_count == 1
    assert result.repair_queued_count == 0
    paper = json.loads(cache_path.read_text(encoding="utf-8"))["papers"][0]
    assert paper["taskRefs"][0]["confidence"] == 0.9
    assert paper["methodRefs"][0]["area"] == "Fine-Tuning"
    assert paper["methodRefs"][0]["confidence"] == 0.9
    assert paper["benchmarks"][0]["confidence"] == 0.9


def test_paper_classification_backfill_falls_back_to_summary_and_queues_repair_when_pdf_fails(tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    cache_path.write_text(
        json.dumps(
            {
                "source": "test-cache",
                "papers": [
                    {
                        "id": "arxiv-2605.00012",
                        "title": "Summary Fallback Paper",
                        "abstractSnippet": "An agent paper with enough summary evidence.",
                        "authors": ["A"],
                        "publishedAt": "2026-05-20T00:00:00Z",
                        "paperUrl": "https://arxiv.org/abs/2605.00012",
                        "pdfUrl": "https://arxiv.org/pdf/2605.00012",
                        "repoUrl": "https://github.com/example/summary-agent",
                        "githubStars": 120,
                        "taskRefs": [{"slug": "legacy-task", "name": "Legacy Task"}],
                        "methodRefs": [{"slug": "legacy-method", "name": "Legacy Method"}],
                        "isPublished": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    service = PaperIngestApplicationService(
        source_service=_FakeSourceService([]),
        github_connector=_FakeGithubConnector(stars=120),
        papers_data_path=cache_path,
        state_dir=tmp_path / "state",
        text_extraction_repository=TextExtractionRepository(tmp_path / "text"),
        pdf_fetcher=lambda url, max_bytes: b"%PDF fake",
        pdf_processor=_FailingPdfProcessor(ValueError("broken pdf")),
        llm_client_factory=lambda route: _FakeLLMClient(
            {
                "primaryTaskGroup": "agents",
                "taskRefs": [{"slug": "agent-task-completion", "name": "Agent Task Completion", "group": "agents", "confidence": 0.91}],
                "methodRefs": [{"slug": "prompting", "name": "Prompting", "area": "Prompt Engineering", "confidence": 0.9}],
                "confidence": 0.9,
            }
        ),
        config=PaperIngestConfig(candidate_limit=100, min_github_stars=50, auto_taxonomy_confidence=0.85),
        clock=_fixed_clock,
    )

    result = service.backfill_published_classification(run_id="backfill-pdf-fallback", batch_size=1)

    assert result.updated_count == 1
    assert result.repair_queued_count == 1
    repair = service.get_ops_state()["repairQueue"][0]
    assert repair["errorCode"] == "pdf_fetch_failed"
    assert repair["context"]["fallback"] == "summary"
    paper = json.loads(cache_path.read_text(encoding="utf-8"))["papers"][0]
    assert paper["classification"]["backfillTextSource"] == "summary"
    assert paper["classification"]["fullTextAvailable"] is False
    assert paper["classification"]["schemaVersion"] == "paper_ingest_classification_v2"


def test_paper_classification_backfill_flushes_completed_papers_before_later_failures(tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    cache_path.write_text(
        json.dumps(
            {
                "source": "test-cache",
                "papers": [
                    {
                        "id": "paper-ok",
                        "title": "First Paper",
                        "abstractSnippet": "First paper.",
                        "paperUrl": "https://arxiv.org/abs/2605.00013",
                        "repoUrl": "https://github.com/example/first",
                        "githubStars": 120,
                        "taskRefs": [{"slug": "legacy-task", "name": "Legacy Task"}],
                        "methodRefs": [{"slug": "legacy-method", "name": "Legacy Method"}],
                        "isPublished": True,
                    },
                    {
                        "id": "paper-fail",
                        "title": "Second Paper",
                        "abstractSnippet": "Second paper.",
                        "paperUrl": "https://arxiv.org/abs/2605.00014",
                        "repoUrl": "https://github.com/example/second",
                        "githubStars": 120,
                        "taskRefs": [{"slug": "legacy-task", "name": "Legacy Task"}],
                        "methodRefs": [{"slug": "legacy-method", "name": "Legacy Method"}],
                        "isPublished": True,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    text_repo = TextExtractionRepository(tmp_path / "text")
    for paper_id in ("paper-ok", "paper-fail"):
        text_repo.write_sections(
            paper_id,
            "source-hash",
            [{"title": "Body", "textExcerpt": "Agent paper evidence.", "sectionType": "body"}],
            cached_at="2026-05-27T08:00:00Z",
        )
    llm_client = _SequencedLLMClient(
        [
            {
                "primaryTaskGroup": "agents",
                "taskRefs": [{"slug": "agents", "name": "Agents", "group": "agents", "confidence": 0.91}],
                "methodRefs": [{"slug": "prompting", "name": "Prompting", "area": "Prompt Engineering", "confidence": 0.9}],
                "confidence": 0.9,
            },
            RuntimeError("temporary classifier failure"),
        ]
    )
    service = PaperIngestApplicationService(
        source_service=_FakeSourceService([]),
        github_connector=_FakeGithubConnector(stars=120),
        papers_data_path=cache_path,
        state_dir=tmp_path / "state",
        text_extraction_repository=text_repo,
        llm_client_factory=lambda route: llm_client,
        config=PaperIngestConfig(candidate_limit=100, min_github_stars=50, auto_taxonomy_confidence=0.85),
        clock=_fixed_clock,
    )

    result = service.backfill_published_classification(run_id="backfill-partial", batch_size=25)

    assert result.updated_count == 1
    assert result.repair_queued_count == 1
    papers = json.loads(cache_path.read_text(encoding="utf-8"))["papers"]
    assert papers[0]["classification"]["schemaVersion"] == "paper_ingest_classification_v2"
    assert "classification" not in papers[1]


def test_paper_classification_backfill_blocks_classifier_credentials(tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    cache_path.write_text(
        json.dumps(
            {
                "source": "test-cache",
                "papers": [
                    {
                        "id": "paper-blocked",
                        "title": "Blocked Paper",
                        "abstractSnippet": "Agent paper.",
                        "paperUrl": "https://arxiv.org/abs/2605.00015",
                        "repoUrl": "https://github.com/example/blocked",
                        "githubStars": 120,
                        "taskRefs": [{"slug": "legacy-task", "name": "Legacy Task"}],
                        "methodRefs": [{"slug": "legacy-method", "name": "Legacy Method"}],
                        "isPublished": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    text_repo = TextExtractionRepository(tmp_path / "text")
    text_repo.write_sections(
        "paper-blocked",
        "source-hash",
        [{"title": "Body", "textExcerpt": "Agent paper evidence.", "sectionType": "body"}],
        cached_at="2026-05-27T08:00:00Z",
    )
    service = PaperIngestApplicationService(
        source_service=_FakeSourceService([]),
        github_connector=_FakeGithubConnector(stars=120),
        papers_data_path=cache_path,
        state_dir=tmp_path / "state",
        text_extraction_repository=text_repo,
        llm_client_factory=lambda route: _FailingLLMClient(LLMConfigurationError("missing API key")),
        config=PaperIngestConfig(candidate_limit=100, min_github_stars=50, auto_taxonomy_confidence=0.85),
        clock=_fixed_clock,
    )

    result = service.backfill_published_classification(run_id="backfill-blocked")

    assert result.blocked_count == 1
    assert result.repair_queued_count == 0
    blocked = service.get_ops_state()["blockedItems"][0]
    assert blocked["queue"] == "manual_blocked"
    assert blocked["userActionRequired"] is True


def test_paper_ingest_skips_repositories_below_star_threshold(tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    service = _service(
        tmp_path,
        cache_path=cache_path,
        source_items=[_candidate("2605.00003", summary="Code: https://github.com/example/small.")],
        stars=49,
    )

    result = service.run_daily_ingest()

    assert result.published_count == 0
    assert result.skipped_low_stars_count == 1
    assert json.loads(cache_path.read_text(encoding="utf-8"))["papers"] == [] if cache_path.exists() else True


def test_paper_ingest_queues_repair_for_invalid_classifier_json(tmp_path) -> None:
    service = _service(
        tmp_path,
        source_items=[_candidate("2605.00004", summary="Code: https://github.com/example/bad-json.")],
        stars=80,
        llm_client=_FakeRawLLMClient("not json"),
    )

    result = service.run_daily_ingest()
    repair_items = service.get_ops_state()["repairQueue"]

    assert result.repair_queued_count == 1
    assert result.blocked_count == 0
    assert repair_items[0]["queue"] == "agent_repair"
    assert repair_items[0]["errorCode"] == "classifier_json_invalid"
    assert repair_items[0]["userActionRequired"] is False


def test_paper_ingest_queues_repair_for_invalid_controlled_taxonomy(tmp_path) -> None:
    service = _service(
        tmp_path,
        source_items=[_candidate("2605.00009", summary="Code: https://github.com/example/invalid-taxonomy.")],
        stars=80,
        llm_payload={
            "primaryTaskGroup": "generic-ai",
            "taskRefs": [{"slug": "generic", "name": "Generic AI", "group": "generic-ai", "confidence": 0.94}],
            "methodRefs": [{"slug": "invented", "name": "Invented Method", "area": "Invented Area", "confidence": 0.94}],
            "benchmarks": [{"name": "MMLU", "category": "made-up-benchmark", "metric": "accuracy", "value": "88", "confidence": 0.94}],
            "confidence": 0.94,
        },
    )

    result = service.run_daily_ingest()
    repair_items = service.get_ops_state()["repairQueue"]

    assert result.published_count == 0
    assert result.repair_queued_count == 1
    assert repair_items[0]["errorCode"] == "classification_empty"
    low_confidence_item = next(item for item in repair_items if item["errorCode"] == "classification_low_confidence")
    reasons = {
        item["reason"]
        for item in low_confidence_item.get("context", {}).get("lowConfidenceItems", [])
    }
    assert "missing_or_invalid_task_group" in reasons or "missing_or_invalid_method_collection" in reasons


def test_paper_ingest_blocks_only_credential_permission_or_account_failures(tmp_path) -> None:
    service = _service(
        tmp_path,
        source_items=[_candidate("2605.00005", summary="Code: https://github.com/example/no-key.")],
        stars=80,
        llm_client=_FailingLLMClient(LLMConfigurationError("missing API key")),
    )

    result = service.run_daily_ingest()
    blocked = service.get_ops_state()["blockedItems"]

    assert result.blocked_count == 1
    assert blocked[0]["queue"] == "manual_blocked"
    assert blocked[0]["userActionRequired"] is True


def test_paper_ingest_repairs_non_credential_classifier_configuration_failures(tmp_path) -> None:
    service = _service(
        tmp_path,
        source_items=[_candidate("2605.00008", summary="Code: https://github.com/example/json-config.")],
        stars=80,
        llm_client=_FailingLLMClient(LLMConfigurationError("dashscope structured output is not valid JSON")),
    )

    result = service.run_daily_ingest()
    repair = service.get_ops_state()["repairQueue"]
    blocked = service.get_ops_state()["blockedItems"]

    assert result.repair_queued_count == 1
    assert result.blocked_count == 0
    assert repair[0]["errorCode"] == "classifier_unavailable"
    assert repair[0]["queue"] == "agent_repair"
    assert blocked == []


def test_paper_ingest_ops_reclassifies_historical_soft_blockers(tmp_path) -> None:
    service = _service(
        tmp_path,
        source_items=[],
    )
    service.state.record_blocked_item(
        {
            "itemId": "soft-blocker",
            "runId": "old-run",
            "paperId": "paper-1",
            "title": "Old soft blocker",
            "step": "classify",
            "errorCode": "classifier_unavailable",
            "errorMessage": "dashscope structured output is not valid JSON",
            "queue": "manual_blocked",
            "status": "blocked",
            "reason": "credential_permission_or_account_block",
            "userActionRequired": True,
            "createdAt": "2026-05-27T00:00:00Z",
        }
    )

    ops = service.get_ops_state()

    assert ops["blockedItems"] == []
    assert ops["repairQueue"][0]["itemId"] == "soft-blocker"
    assert ops["repairQueue"][0]["queue"] == "agent_repair"
    assert ops["repairQueue"][0]["reclassifiedFrom"] == "manual_blocked"
    assert ops["repairQueue"][0]["userActionRequired"] is False


def test_paper_ingest_uses_candidate_limit_100(tmp_path) -> None:
    source_items = [_candidate(f"2605.{index:05d}", summary="No repository.") for index in range(120)]
    source = _FakeSourceService(source_items)
    service = PaperIngestApplicationService(
        source_service=source,
        github_connector=_FakeGithubConnector(stars=80),
        papers_data_path=tmp_path / "papers.json",
        state_dir=tmp_path / "state",
        pdf_fetcher=lambda url, max_bytes: b"%PDF fake",
        pdf_processor=_FakePdfProcessor("No repository."),
        llm_client_factory=lambda route: _FakeLLMClient({}),
        config=PaperIngestConfig(candidate_limit=100),
        clock=_fixed_clock,
    )

    result = service.run_daily_ingest()

    assert source.calls == [("cat:cs.AI OR cat:cs.LG OR cat:cs.CL", 100)]
    assert result.candidate_count == 100
    assert result.processed_count == 100
    assert result.skipped_no_github_count == 100


def test_paper_ingest_persists_running_state_before_fetching_candidates(tmp_path) -> None:
    state_dir = tmp_path / "state"
    source = _InspectingSourceService(state_dir)
    service = PaperIngestApplicationService(
        source_service=source,
        github_connector=_FakeGithubConnector(stars=80),
        papers_data_path=tmp_path / "papers.json",
        state_dir=state_dir,
        pdf_fetcher=lambda url, max_bytes: b"%PDF fake",
        pdf_processor=_FakePdfProcessor("No repository."),
        llm_client_factory=lambda route: _FakeLLMClient({}),
        config=PaperIngestConfig(candidate_limit=100),
        clock=_fixed_clock,
    )

    result = service.run_daily_ingest(run_id="visible-running-run")

    assert source.saw_running_state is True
    assert result.status == "succeeded"
    assert service.get_ops_state()["runs"][0]["status"] == "succeeded"


def test_paper_ingest_default_uses_dedicated_arxiv_api_connector(tmp_path) -> None:
    arxiv_connector = _FakeArxivConnector(
        [_candidate("2605.00006", summary="No explicit repository.")]
    )
    service = PaperIngestApplicationService(
        arxiv_connector=arxiv_connector,
        github_connector=_FakeGithubConnector(stars=80),
        papers_data_path=tmp_path / "papers.json",
        state_dir=tmp_path / "state",
        pdf_fetcher=lambda url, max_bytes: b"%PDF fake",
        pdf_processor=_FakePdfProcessor("No repository."),
        llm_client_factory=lambda route: _FakeLLMClient({}),
        config=PaperIngestConfig(candidate_limit=100),
        clock=_fixed_clock,
    )

    result = service.run_daily_ingest()

    assert result.candidate_count == 1
    assert result.skipped_no_github_count == 1
    assert arxiv_connector.calls[0]["query"] == "cat:cs.AI OR cat:cs.LG OR cat:cs.CL"
    assert arxiv_connector.calls[0]["limit"] == 100
    assert arxiv_connector.calls[0]["respect_robots"] is False


def test_paper_ingest_records_arxiv_fetch_failure_in_agent_repair_queue(tmp_path) -> None:
    service = PaperIngestApplicationService(
        arxiv_connector=_FailingArxivConnector("robots.txt disallows fetching arXiv API"),
        github_connector=_FakeGithubConnector(stars=80),
        papers_data_path=tmp_path / "papers.json",
        state_dir=tmp_path / "state",
        config=PaperIngestConfig(candidate_limit=100),
        clock=_fixed_clock,
    )

    result = service.run_daily_ingest(run_id="arxiv-fetch-failure")
    repair_items = service.get_ops_state()["repairQueue"]

    assert result.status == "partial"
    assert result.failure_count == 1
    assert result.repair_queued_count == 1
    assert repair_items[0]["step"] == "arxiv_fetch"
    assert repair_items[0]["queue"] == "agent_repair"
    assert repair_items[0]["userActionRequired"] is False


def test_paper_ingest_falls_back_to_cached_arxiv_candidates_when_api_is_limited(tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    cache_path.write_text(
        json.dumps(
            {
                "source": "arxiv",
                "papers": [
                    {
                        "id": "arxiv-2605.00007",
                        "title": "Cached Paper",
                        "abstractSnippet": "No repository in the cached abstract.",
                        "paperUrl": "https://arxiv.org/abs/2605.00007v1",
                        "pdfUrl": "https://arxiv.org/pdf/2605.00007v1",
                        "authors": ["A. Researcher"],
                        "tags": ["cs.AI"],
                        "publishedAt": "2026-05-27T00:00:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    service = PaperIngestApplicationService(
        arxiv_connector=_FailingArxivConnector("HTTP Error 429: Unknown Error"),
        github_connector=_FakeGithubConnector(stars=80),
        papers_data_path=cache_path,
        state_dir=tmp_path / "state",
        pdf_fetcher=lambda url, max_bytes: b"%PDF fake",
        pdf_processor=_FakePdfProcessor("No repository."),
        llm_client_factory=lambda route: _FakeLLMClient({}),
        config=PaperIngestConfig(candidate_limit=100),
        clock=_fixed_clock,
    )

    result = service.run_daily_ingest(run_id="cached-fallback")
    repair_items = service.get_ops_state()["repairQueue"]

    assert result.status == "partial"
    assert result.candidate_count == 1
    assert result.processed_count == 1
    assert result.skipped_no_github_count == 1
    assert result.repair_queued_count == 1
    assert repair_items[0]["context"]["fallback"] == "papers_cache"


def _service(
    tmp_path: Path,
    *,
    cache_path: Path | None = None,
    source_items: list[RawSourceItem],
    pdf_text: str = "Code: https://github.com/example/default. Task and method evidence.",
    stars: int = 80,
    llm_payload: dict[str, Any] | None = None,
    llm_client: Any | None = None,
    citation_client: Any | None = None,
    paper_analysis_orchestrator: Any | None = None,
    config: PaperIngestConfig | None = None,
) -> PaperIngestApplicationService:
    return PaperIngestApplicationService(
        source_service=_FakeSourceService(source_items),
        github_connector=_FakeGithubConnector(stars=stars),
        papers_data_path=cache_path or tmp_path / "papers.json",
        state_dir=tmp_path / "state",
        text_extraction_repository=TextExtractionRepository(tmp_path / "text"),
        pdf_fetcher=lambda url, max_bytes: b"%PDF fake",
        pdf_processor=_FakePdfProcessor(pdf_text),
        citation_client=citation_client or _FakeCitationClient({}),
        llm_client_factory=lambda route: llm_client
        or _FakeLLMClient(
            llm_payload
            or {
                "primaryTaskGroup": "agents",
                "taskRefs": [{"slug": "agents", "name": "Agents", "group": "agents", "confidence": 0.9}],
                "methodRefs": [{"slug": "rag", "name": "Retrieval Augmented Generation", "area": "Language Models", "confidence": 0.9}],
                "confidence": 0.9,
            }
        ),
        paper_analysis_orchestrator=paper_analysis_orchestrator,
        config=config or PaperIngestConfig(candidate_limit=100, min_github_stars=50, auto_taxonomy_confidence=0.85),
        clock=_fixed_clock,
    )


def _candidate(arxiv_id: str, *, summary: str) -> RawSourceItem:
    return RawSourceItem(
        source_item_id=f"raw-{arxiv_id}",
        source_id="arxiv",
        source_name="arXiv",
        source_type="arxiv",
        title=f"Paper {arxiv_id}",
        url=f"https://arxiv.org/abs/{arxiv_id}",
        fetched_at=_fixed_clock(),
        published_at=_fixed_clock(),
        summary=summary,
        raw_content="",
        authors=["A. Researcher"],
        tags=["cs.AI"],
        language="en",
        metadata={"arxiv_id": arxiv_id, "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}.pdf"},
    )


def _fixed_clock() -> datetime:
    return datetime(2026, 5, 27, 8, 0, 0, tzinfo=UTC)


class _FakeSourceResult:
    def __init__(self, items: list[RawSourceItem]) -> None:
        self.items = items
        self.errors: list[Any] = []


class _FakeSourceService:
    def __init__(self, items: list[RawSourceItem]) -> None:
        self.items = items
        self.calls: list[tuple[str, int]] = []

    def fetch_arxiv(self, *, query: str, limit: int) -> _FakeSourceResult:
        self.calls.append((query, limit))
        return _FakeSourceResult(self.items[:limit])


class _InspectingSourceService:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.saw_running_state = False

    def fetch_arxiv(self, *, query: str, limit: int) -> _FakeSourceResult:
        payload = json.loads((self.state_dir / "ingest-runs.json").read_text(encoding="utf-8"))
        run = payload["runs"][0]
        self.saw_running_state = (
            run["runId"] == "visible-running-run"
            and run["status"] == "running"
            and run["candidateCount"] == 0
            and run["processedCount"] == 0
        )
        return _FakeSourceResult([])


class _FakeArxivConnector:
    def __init__(self, items: list[RawSourceItem]) -> None:
        self.items = items
        self.calls: list[dict[str, Any]] = []

    def fetch(self, source, *, query: str, limit: int):
        self.calls.append(
            {
                "query": query,
                "limit": limit,
                "respect_robots": source.respect_robots,
                "url": source.url,
            }
        )
        return self.items[:limit], []


class _FailingArxivConnector:
    def __init__(self, message: str) -> None:
        self.message = message

    def fetch(self, source, *, query: str, limit: int):
        return [], [
            SourceError(
                source_id=source.source_id,
                source_name=source.name,
                error_type="robots_disallowed",
                error_message=self.message,
                url=source.url,
                retryable=True,
                metadata={"phase": "fetch"},
            )
        ]


class _FakeGithubConnector:
    def __init__(self, *, stars: int) -> None:
        self.stars = stars
        self.calls: list[dict[str, Any]] = []

    def fetch_repository_metadata(self, source, *, repository: str):
        self.calls.append(
            {
                "repository": repository,
                "respect_robots": source.respect_robots,
            }
        )
        return (
            GithubRepositoryMetadata(
                repository_id=1,
                full_name=repository,
                html_url=f"https://github.com/{repository}",
                description=None,
                language="Python",
                stargazers_count=self.stars,
                forks_count=1,
                open_issues_count=0,
                archived=False,
                disabled=False,
                visibility="public",
                topics=[],
                pushed_at=_fixed_clock(),
                updated_at=_fixed_clock(),
            ),
            [],
        )


class _FakeCitationClient:
    def __init__(
        self,
        citations: Mapping[str, PaperCitationMetadata],
        *,
        error: Exception | None = None,
    ) -> None:
        self.citations = dict(citations)
        self.error = error
        self.calls: list[list[str]] = []

    def fetch_by_dois(self, dois):
        normalized = [str(doi).strip().lower() for doi in dois]
        self.calls.append(normalized)
        if self.error is not None:
            raise self.error
        return {doi: self.citations[doi] for doi in normalized if doi in self.citations}


class _FakePdfProcessor:
    def __init__(self, full_text: str) -> None:
        self.full_text = full_text

    def extract(self, pdf_bytes: bytes, *, paper_id: str, pdf_url: str, thumbnail_path: Path) -> PaperPdfExtraction:
        thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
        thumbnail_path.write_bytes(b"png")
        return PaperPdfExtraction(
            full_text=self.full_text,
            sections=(
                {
                    "title": "Page 1",
                    "level": 1,
                    "pageStart": 1,
                    "pageEnd": 1,
                    "textExcerpt": self.full_text,
                    "sectionType": "abstract",
                },
            ),
            thumbnail_path=thumbnail_path,
            page_count=1,
        )


class _FailingPdfProcessor:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def extract(self, pdf_bytes: bytes, *, paper_id: str, pdf_url: str, thumbnail_path: Path) -> PaperPdfExtraction:
        raise self.exc


class _FakeLLMClient:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = payload
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        class Response:
            content = ""

        response = Response()
        response.content = json.dumps(self.payload)
        return response


class _FakePaperAnalysisOrchestrator:
    def __init__(self, final_profile: Mapping[str, Any]) -> None:
        self.final_profile = dict(final_profile)
        self.requests: list[Any] = []

    def analyze_paper(self, request) -> PaperAnalysisResult:
        self.requests.append(request)
        return PaperAnalysisResult(
            paper_id=request.paper_id,
            run_id=request.run_id,
            session_id=request.session_id,
            final_profile=self.final_profile,
            agent_outputs={"paper_final_profile": self.final_profile},
        )


class _FailingPaperAnalysisOrchestrator:
    def analyze_paper(self, request) -> PaperAnalysisResult:
        raise RuntimeError("agent analysis failed")


class _SequencedLLMClient:
    def __init__(self, outcomes: list[Mapping[str, Any] | Exception]) -> None:
        self.outcomes = outcomes
        self.index = 0

    def complete(self, request):
        outcome = self.outcomes[min(self.index, len(self.outcomes) - 1)]
        self.index += 1
        if isinstance(outcome, Exception):
            raise outcome

        class Response:
            content = ""

        response = Response()
        response.content = json.dumps(outcome)
        return response


class _FakeRawLLMClient:
    def __init__(self, content: str) -> None:
        self.content = content

    def complete(self, request):
        class Response:
            content = ""

        response = Response()
        response.content = self.content
        return response


class _FailingLLMClient:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def complete(self, request):
        raise self.exc
