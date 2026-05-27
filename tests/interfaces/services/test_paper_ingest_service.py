import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from framework.llm import LLMConfigurationError
from infrastructure.external.sources.github import GithubRepositoryMetadata
from infrastructure.external.sources.models import RawSourceItem, SourceError
from interfaces.services.paper_ingest_service import (
    PaperIngestApplicationService,
    PaperIngestConfig,
    PaperPdfExtraction,
)
from interfaces.services.paper_reader_cache_repository import TextExtractionRepository


def test_paper_ingest_publishes_github_arxiv_paper_with_thumbnail_and_taxonomy(tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    state_dir = tmp_path / "state"
    text_repo = TextExtractionRepository(tmp_path / "text")
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
        github_connector=_FakeGithubConnector(stars=88),
        papers_data_path=cache_path,
        state_dir=state_dir,
        text_extraction_repository=text_repo,
        pdf_fetcher=lambda url, max_bytes: b"%PDF fake",
        pdf_processor=_FakePdfProcessor("The paper studies agent planning and reports MMLU 88."),
        llm_client_factory=lambda route: _FakeLLMClient(
            {
                "taskRefs": [{"slug": "agent-planning", "name": "Agent Planning", "confidence": 0.93, "evidence": "planning task"}],
                "methodRefs": [{"slug": "tree-search", "name": "Tree Search", "confidence": 0.9, "evidence": "method section"}],
                "benchmarks": [{"name": "MMLU", "metric": "accuracy", "value": "88", "taskSlug": "agent-planning", "confidence": 0.91}],
                "confidence": 0.92,
                "evidenceSummary": "The paper reports code, task, method, and benchmark evidence.",
            }
        ),
        config=PaperIngestConfig(candidate_limit=100, min_github_stars=50, auto_taxonomy_confidence=0.85),
        clock=_fixed_clock,
    )

    result = service.run_daily_ingest()

    assert source.calls == [("cat:cs.AI OR cat:cs.LG OR cat:cs.CL", 100)]
    assert result.published_count == 1
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    paper = payload["papers"][0]
    assert paper["isPublished"] is True
    assert paper["repoUrl"] == "https://github.com/example/agent-paper"
    assert paper["githubStars"] == 88
    assert paper["thumbnailUrl"].startswith("/api/papers/assets/thumbnails/")
    assert paper["taskRefs"][0]["slug"] == "agent-planning"
    assert paper["methodRefs"][0]["slug"] == "tree-search"
    assert paper["benchmarks"][0]["name"] == "MMLU"
    assert paper["classification"]["confidence"] == 0.92
    assert (state_dir / "taxonomy-events.json").exists()
    assert text_repo.read_latest_sections("arxiv-2605.00001")


def test_paper_ingest_extracts_explicit_github_from_pdf_text(tmp_path) -> None:
    cache_path = tmp_path / "papers.json"
    service = _service(
        tmp_path,
        cache_path=cache_path,
        source_items=[_candidate("2605.00002", summary="No repository in the abstract.")],
        pdf_text="Implementation: https://github.com/example/pdf-code.",
        stars=64,
        llm_payload={
            "taskRefs": [{"slug": "code-generation", "name": "Code Generation", "confidence": 0.9}],
            "methodRefs": [{"slug": "self-repair", "name": "Self Repair", "confidence": 0.9}],
            "confidence": 0.9,
        },
    )

    result = service.run_daily_ingest()

    assert result.published_count == 1
    paper = json.loads(cache_path.read_text(encoding="utf-8"))["papers"][0]
    assert paper["repoUrl"] == "https://github.com/example/pdf-code"


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
) -> PaperIngestApplicationService:
    return PaperIngestApplicationService(
        source_service=_FakeSourceService(source_items),
        github_connector=_FakeGithubConnector(stars=stars),
        papers_data_path=cache_path or tmp_path / "papers.json",
        state_dir=tmp_path / "state",
        text_extraction_repository=TextExtractionRepository(tmp_path / "text"),
        pdf_fetcher=lambda url, max_bytes: b"%PDF fake",
        pdf_processor=_FakePdfProcessor(pdf_text),
        llm_client_factory=lambda route: llm_client
        or _FakeLLMClient(
            llm_payload
            or {
                "taskRefs": [{"slug": "agents", "name": "Agents", "confidence": 0.9}],
                "methodRefs": [{"slug": "rag", "name": "Retrieval Augmented Generation", "confidence": 0.9}],
                "confidence": 0.9,
            }
        ),
        config=PaperIngestConfig(candidate_limit=100, min_github_stars=50, auto_taxonomy_confidence=0.85),
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

    def fetch_repository_metadata(self, source, *, repository: str):
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


class _FakeLLMClient:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = payload

    def complete(self, request):
        class Response:
            content = ""

        response = Response()
        response.content = json.dumps(self.payload)
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
