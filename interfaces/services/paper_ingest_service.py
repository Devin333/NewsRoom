from __future__ import annotations

import hashlib
import html
import json
import os
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as _tz
UTC = _tz.utc
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from business.boards.paper_radar.public_mapper import sanitize_public_payload
from business.boards.paper_radar.agents import PaperAnalysisOrchestrator, PaperAnalysisRequest, paper_session_access_policy
from framework.agent.session import AgentSharedWorkspace, SQLiteAgentSessionStore
from framework.llm import (
    DEFAULT_MODEL_ROUTE_ID,
    LLMConfigurationError,
    LLMMessage,
    LLMProviderError,
    LLMRequest,
    build_openai_compatible_client_from_config,
)
from infrastructure.external.sources import (
    ARXIV_API_URL,
    GITHUB_API_URL,
    SourceFetchPolicy,
    default_arxiv_connector,
    default_github_connector,
)
from infrastructure.external.sources.github import GithubRepository, GithubRepositoryMetadata
from infrastructure.external.sources.models import RawSourceItem, SourceDefinition
from interfaces.services.json_file_store import locked_json_file, read_json_object, read_json_object_unlocked, write_json_object, write_json_object_unlocked
from interfaces.services.paper_reader_cache_repository import TextExtractionRepository
from interfaces.services.paper_service import PAPERS_DATA_PATH_ENV
from interfaces.services.paper_taxonomy_categories import (
    AI_TASK_GROUPS,
    BENCHMARK_CATEGORIES,
    benchmark_category_options,
    load_pwc_method_collections,
    method_collection_options,
    normalize_ai_task_group,
    normalize_benchmark_category,
    normalize_method_collection,
    task_group_options,
)


PAPER_INGEST_TASK_TYPE = "papers.ingest_github_arxiv_daily"
PAPERS_INGEST_STATE_DIR_ENV = "NEWSROOM_PAPERS_INGEST_STATE_DIR"
PAPERS_INGEST_CANDIDATE_LIMIT_ENV = "NEWSROOM_PAPERS_INGEST_CANDIDATE_LIMIT"
PAPERS_INGEST_MIN_GITHUB_STARS_ENV = "NEWSROOM_PAPERS_INGEST_MIN_GITHUB_STARS"
PAPERS_INGEST_AUTO_TAXONOMY_CONFIDENCE_ENV = "NEWSROOM_PAPERS_INGEST_AUTO_TAXONOMY_CONFIDENCE"
PAPERS_INGEST_ARXIV_QUERY_ENV = "NEWSROOM_PAPERS_INGEST_ARXIV_QUERY"
PAPERS_INGEST_ARXIV_USER_AGENT_ENV = "NEWSROOM_PAPERS_INGEST_ARXIV_USER_AGENT"
PAPERS_CLASSIFIER_MODEL_ROUTE_ENV = "NEWSROOM_PAPERS_CLASSIFIER_MODEL_ROUTE"
PAPERS_CLASSIFIER_MAX_CHARS_ENV = "NEWSROOM_PAPERS_CLASSIFIER_MAX_CHARS"
PAPERS_USE_LEGACY_CLASSIFIER_FALLBACK_ENV = "NEWSROOM_PAPERS_USE_LEGACY_CLASSIFIER_FALLBACK"
PAPERS_AGENT_SESSION_STORE_PATH_ENV = "NEWSROOM_PAPERS_AGENT_SESSION_STORE_PATH"
PAPERS_AGENT_ANALYSIS_REQUIRED_ENV = "NEWSROOM_PAPERS_AGENT_ANALYSIS_REQUIRED"
PAPERS_PDF_MAX_BYTES_ENV = "NEWSROOM_PAPERS_PDF_MAX_BYTES"
PAPERS_OPENALEX_API_KEY_ENV = "OPENALEX_API_KEY"
PAPERS_OPENALEX_API_KEY_FALLBACK_ENV = "NEWSROOM_OPENALEX_API_KEY"
PAPERS_OPENALEX_MAILTO_ENV = "NEWSROOM_OPENALEX_MAILTO"

DEFAULT_CANDIDATE_LIMIT = 100
DEFAULT_MIN_GITHUB_STARS = 50
DEFAULT_AUTO_TAXONOMY_CONFIDENCE = 0.85
DEFAULT_ARXIV_QUERY = "cat:cs.AI OR cat:cs.LG OR cat:cs.CL"
DEFAULT_ARXIV_USER_AGENT = "NewsRoom/0.1 paper-ingest contact: local-dev"
DEFAULT_CLASSIFIER_MAX_CHARS = 120_000
DEFAULT_PDF_MAX_BYTES = 40_000_000
DEFAULT_REPAIR_DELAY_MINUTES = 30
DEFAULT_OPENALEX_BATCH_SIZE = 50
OPENALEX_WORKS_API = "https://api.openalex.org/works"

_GITHUB_REPO_PATTERN = re.compile(r"https?://(?:www\.)?github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_ARXIV_ID_PATTERN = re.compile(r"arxiv\.org/(?:abs|pdf)/([^/?#]+)", flags=re.IGNORECASE)
_HARD_BLOCK_HINTS = (
    "api key",
    "apikey",
    "authorization",
    "unauthorized",
    "forbidden",
    "permission",
    "quota",
    "billing",
    "insufficient_quota",
    "account",
    "banned",
    "401",
    "403",
)


class PaperIngestError(RuntimeError):
    def __init__(self, message: str, *, code: str, step: str, retryable: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.step = step
        self.retryable = retryable


class PaperIngestHardBlock(PaperIngestError):
    pass


@dataclass(frozen=True)
class PaperIngestConfig:
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT
    min_github_stars: int = DEFAULT_MIN_GITHUB_STARS
    auto_taxonomy_confidence: float = DEFAULT_AUTO_TAXONOMY_CONFIDENCE
    arxiv_query: str = DEFAULT_ARXIV_QUERY
    arxiv_user_agent: str = DEFAULT_ARXIV_USER_AGENT
    classifier_model_route: str = DEFAULT_MODEL_ROUTE_ID
    classifier_max_chars: int = DEFAULT_CLASSIFIER_MAX_CHARS
    pdf_max_bytes: int = DEFAULT_PDF_MAX_BYTES
    use_legacy_classifier_fallback: bool = True
    agent_session_store_path: str | None = None
    agent_analysis_required: bool = True

    @classmethod
    def from_env(cls) -> PaperIngestConfig:
        return cls(
            candidate_limit=_positive_int_env(PAPERS_INGEST_CANDIDATE_LIMIT_ENV, DEFAULT_CANDIDATE_LIMIT),
            min_github_stars=_positive_int_env(PAPERS_INGEST_MIN_GITHUB_STARS_ENV, DEFAULT_MIN_GITHUB_STARS),
            auto_taxonomy_confidence=_float_env(
                PAPERS_INGEST_AUTO_TAXONOMY_CONFIDENCE_ENV,
                DEFAULT_AUTO_TAXONOMY_CONFIDENCE,
            ),
            arxiv_query=os.environ.get(PAPERS_INGEST_ARXIV_QUERY_ENV, DEFAULT_ARXIV_QUERY).strip()
            or DEFAULT_ARXIV_QUERY,
            arxiv_user_agent=os.environ.get(PAPERS_INGEST_ARXIV_USER_AGENT_ENV, DEFAULT_ARXIV_USER_AGENT).strip()
            or DEFAULT_ARXIV_USER_AGENT,
            classifier_model_route=os.environ.get(PAPERS_CLASSIFIER_MODEL_ROUTE_ENV, DEFAULT_MODEL_ROUTE_ID).strip()
            or DEFAULT_MODEL_ROUTE_ID,
            classifier_max_chars=_positive_int_env(PAPERS_CLASSIFIER_MAX_CHARS_ENV, DEFAULT_CLASSIFIER_MAX_CHARS),
            pdf_max_bytes=_positive_int_env(PAPERS_PDF_MAX_BYTES_ENV, DEFAULT_PDF_MAX_BYTES),
            use_legacy_classifier_fallback=_bool_env(PAPERS_USE_LEGACY_CLASSIFIER_FALLBACK_ENV, True),
            agent_session_store_path=_optional_env(PAPERS_AGENT_SESSION_STORE_PATH_ENV),
            agent_analysis_required=_bool_env(PAPERS_AGENT_ANALYSIS_REQUIRED_ENV, True),
        )

    def with_overrides(
        self,
        *,
        candidate_limit: int | None = None,
        min_github_stars: int | None = None,
    ) -> PaperIngestConfig:
        return PaperIngestConfig(
            candidate_limit=_positive_int(candidate_limit) or self.candidate_limit,
            min_github_stars=_positive_int(min_github_stars) or self.min_github_stars,
            auto_taxonomy_confidence=self.auto_taxonomy_confidence,
            arxiv_query=self.arxiv_query,
            arxiv_user_agent=self.arxiv_user_agent,
            classifier_model_route=self.classifier_model_route,
            classifier_max_chars=self.classifier_max_chars,
            pdf_max_bytes=self.pdf_max_bytes,
            use_legacy_classifier_fallback=self.use_legacy_classifier_fallback,
            agent_session_store_path=self.agent_session_store_path,
            agent_analysis_required=self.agent_analysis_required,
        )


@dataclass(frozen=True)
class PaperPdfExtraction:
    full_text: str
    sections: tuple[Mapping[str, Any], ...]
    thumbnail_path: Path | None = None
    page_count: int = 0


@dataclass(frozen=True)
class PaperIngestRunResult:
    run_id: str
    status: str
    started_at: str
    finished_at: str
    candidate_limit: int
    min_github_stars: int
    auto_taxonomy_confidence: float
    candidate_count: int
    processed_count: int
    published_count: int
    skipped_no_github_count: int
    skipped_low_stars_count: int
    repair_queued_count: int
    blocked_count: int
    failure_count: int
    published_paper_ids: tuple[str, ...]
    errors: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "status": self.status,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "candidateLimit": self.candidate_limit,
            "minGithubStars": self.min_github_stars,
            "autoTaxonomyConfidence": self.auto_taxonomy_confidence,
            "candidateCount": self.candidate_count,
            "processedCount": self.processed_count,
            "publishedCount": self.published_count,
            "skippedNoGithubCount": self.skipped_no_github_count,
            "skippedLowStarsCount": self.skipped_low_stars_count,
            "repairQueuedCount": self.repair_queued_count,
            "blockedCount": self.blocked_count,
            "failureCount": self.failure_count,
            "publishedPaperIds": list(self.published_paper_ids),
            "errors": [dict(item) for item in self.errors],
        }


@dataclass(frozen=True)
class PaperClassificationBackfillResult:
    run_id: str
    started_at: str
    finished_at: str
    batch_size: int
    scanned_count: int
    updated_count: int
    skipped_count: int
    repair_queued_count: int
    blocked_count: int
    updated_paper_ids: tuple[str, ...]
    errors: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "batchSize": self.batch_size,
            "scannedCount": self.scanned_count,
            "updatedCount": self.updated_count,
            "skippedCount": self.skipped_count,
            "repairQueuedCount": self.repair_queued_count,
            "blockedCount": self.blocked_count,
            "updatedPaperIds": list(self.updated_paper_ids),
            "errors": [dict(item) for item in self.errors],
        }


@dataclass(frozen=True)
class PaperCitationMetadata:
    doi: str
    citation_count: int
    openalex_id: str
    display_name: str | None = None

    def to_cache_payload(self, *, fetched_at: str) -> Mapping[str, Any]:
        return sanitize_public_payload(
            {
                "citationCount": self.citation_count,
                "citationDoi": self.doi,
                "openAlexId": self.openalex_id,
                "citationFetchedAt": fetched_at,
                "citationSource": "openalex",
                "citation": {
                    "provider": "openalex",
                    "openAlexId": self.openalex_id,
                    "doi": self.doi,
                    "count": self.citation_count,
                    "displayName": self.display_name,
                    "fetchedAt": fetched_at,
                },
            }
        )


@dataclass(frozen=True)
class PaperCitationBackfillResult:
    run_id: str
    started_at: str
    finished_at: str
    batch_size: int
    scanned_count: int
    updated_count: int
    skipped_count: int
    repair_queued_count: int
    blocked_count: int
    updated_paper_ids: tuple[str, ...]
    errors: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "batchSize": self.batch_size,
            "scannedCount": self.scanned_count,
            "updatedCount": self.updated_count,
            "skippedCount": self.skipped_count,
            "repairQueuedCount": self.repair_queued_count,
            "blockedCount": self.blocked_count,
            "updatedPaperIds": list(self.updated_paper_ids),
            "errors": [dict(item) for item in self.errors],
        }


class PaperOpenAlexCitationClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        mailto: str | None = None,
        opener: Callable[[Request, int], Mapping[str, Any]] | None = None,
    ) -> None:
        self.api_key = (
            api_key
            if api_key is not None
            else os.environ.get(PAPERS_OPENALEX_API_KEY_ENV) or os.environ.get(PAPERS_OPENALEX_API_KEY_FALLBACK_ENV)
        )
        self.mailto = mailto if mailto is not None else os.environ.get(PAPERS_OPENALEX_MAILTO_ENV)
        self.opener = opener or _openalex_fetch_json

    def fetch_by_dois(self, dois: Sequence[str]) -> Mapping[str, PaperCitationMetadata]:
        normalized_dois = _dedupe_strings([_normalize_doi(doi) for doi in dois])
        if not normalized_dois:
            return {}

        params: dict[str, str] = {
            "filter": f"doi:{'|'.join(normalized_dois)}",
            "per-page": str(min(len(normalized_dois), 200)),
            "select": "id,doi,display_name,cited_by_count",
        }
        if self.api_key:
            params["api_key"] = self.api_key
        if self.mailto:
            params["mailto"] = self.mailto
        url = f"{OPENALEX_WORKS_API}?{urlencode(params)}"
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "NewsRoomResearch/0.1 paper-citations",
            },
        )
        try:
            payload = self.opener(request, 45)
        except PaperIngestError:
            raise
        except HTTPError as exc:
            message = _http_error_message(exc)
            if _is_hard_block_error(str(exc.code), message):
                raise PaperIngestHardBlock(message, code="openalex_hard_blocked", step="citation_fetch", retryable=False) from exc
            raise PaperIngestError(message, code="openalex_fetch_failed", step="citation_fetch") from exc
        except (URLError, OSError, ValueError, TimeoutError) as exc:
            raise PaperIngestError(str(exc), code="openalex_fetch_failed", step="citation_fetch") from exc

        results: dict[str, PaperCitationMetadata] = {}
        for item in _sequence(payload.get("results")):
            if not isinstance(item, Mapping):
                continue
            doi = _normalize_doi(item.get("doi"))
            if not doi:
                continue
            citation_count = _int(item.get("cited_by_count"))
            openalex_id = _optional_text(item.get("id"))
            if citation_count is None or citation_count < 0 or not openalex_id:
                continue
            results[doi] = PaperCitationMetadata(
                doi=doi,
                citation_count=citation_count,
                openalex_id=openalex_id,
                display_name=_optional_text(item.get("display_name")),
            )
        return results


class PaperPdfProcessor:
    def extract(
        self,
        pdf_bytes: bytes,
        *,
        paper_id: str,
        pdf_url: str,
        thumbnail_path: Path,
    ) -> PaperPdfExtraction:
        try:
            import fitz  # type: ignore[import-not-found]
        except ImportError as exc:
            raise PaperIngestError(
                "PyMuPDF is required for PDF text extraction and thumbnail generation",
                code="pdf_processor_missing",
                step="pdf_extract",
            ) from exc

        try:
            document = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as exc:  # pragma: no cover - PyMuPDF uses broad exception classes.
            raise PaperIngestError(str(exc), code="pdf_open_failed", step="pdf_extract") from exc

        sections: list[Mapping[str, Any]] = []
        full_text_parts: list[str] = []
        try:
            for index, page in enumerate(document):
                page_number = index + 1
                text = _normalize_space(page.get_text("text"))
                if text:
                    full_text_parts.append(text)
                    sections.append(
                        {
                            "title": f"Page {page_number}",
                            "level": 1,
                            "pageStart": page_number,
                            "pageEnd": page_number,
                            "textExcerpt": text[:10_000],
                            "sectionType": _section_type_from_text(text, page_number),
                        }
                    )
            if len(document) > 0:
                thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
                page = document[0]
                matrix = fitz.Matrix(1.6, 1.6)
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                pixmap.save(str(thumbnail_path))
        finally:
            document.close()

        full_text = "\n\n".join(full_text_parts).strip()
        if not full_text:
            raise PaperIngestError("PDF contained no extractable text", code="pdf_text_empty", step="pdf_extract")
        return PaperPdfExtraction(
            full_text=full_text,
            sections=tuple(sections),
            thumbnail_path=thumbnail_path if thumbnail_path.exists() else None,
            page_count=len(sections),
        )


class PaperIngestApplicationService:
    def __init__(
        self,
        *,
        source_service: Any | None = None,
        arxiv_connector: Any | None = None,
        github_connector: Any | None = None,
        papers_data_path: str | Path | None = None,
        state_dir: str | Path | None = None,
        text_extraction_repository: TextExtractionRepository | None = None,
        pdf_processor: PaperPdfProcessor | None = None,
        pdf_fetcher: Callable[[str, int], bytes] | None = None,
        citation_client: PaperOpenAlexCitationClient | None = None,
        llm_client_factory: Callable[[str], Any] | None = None,
        paper_analysis_orchestrator: PaperAnalysisOrchestrator | None = None,
        config: PaperIngestConfig | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config or PaperIngestConfig.from_env()
        self.source_service = source_service
        self.arxiv_connector = arxiv_connector or default_arxiv_connector(
            fetch_policy=SourceFetchPolicy(
                max_bytes=5_000_000,
                timeout_seconds=60.0,
                respect_robots=False,
                user_agent=self.config.arxiv_user_agent,
            )
        )
        self.github_connector = github_connector or default_github_connector(
            fetch_policy=SourceFetchPolicy(
                max_bytes=5_000_000,
                timeout_seconds=60.0,
                respect_robots=False,
            )
        )
        self.papers_data_path = _papers_data_path(papers_data_path)
        self.state = PaperIngestStateRepository(state_dir)
        self.text_extraction_repository = text_extraction_repository or TextExtractionRepository()
        self.pdf_processor = pdf_processor or PaperPdfProcessor()
        self.pdf_fetcher = pdf_fetcher or _fetch_pdf_bytes
        self.citation_client = citation_client or PaperOpenAlexCitationClient()
        self.llm_client_factory = llm_client_factory or _default_llm_client_factory
        self.paper_analysis_orchestrator = paper_analysis_orchestrator or _default_paper_analysis_orchestrator(self.config)
        self.clock = clock or (lambda: datetime.now(UTC))

    def run_daily_ingest(
        self,
        *,
        candidate_limit: int | None = None,
        min_github_stars: int | None = None,
        run_id: str | None = None,
    ) -> PaperIngestRunResult:
        config = self.config.with_overrides(
            candidate_limit=candidate_limit,
            min_github_stars=min_github_stars,
        )
        started = self.clock()
        normalized_run_id = run_id or f"paper-ingest-{started.strftime('%Y%m%d%H%M%S')}"
        run_state = _new_run_state(normalized_run_id, started=started, config=config)
        self.state.record_run(run_state)
        errors: list[Mapping[str, Any]] = []
        try:
            candidates = self._fetch_candidates(config)
        except PaperIngestHardBlock as exc:
            run_state["blockedCount"] += 1
            errors.append(
                self._handle_run_failure(
                    run_id=normalized_run_id,
                    step=exc.step,
                    error_code=exc.code,
                    error_message=str(exc),
                    hard_block=True,
                )
            )
            return self._finalize_run(run_state, published_ids=[], errors=errors)
        except PaperIngestError as exc:
            candidates = self._cached_arxiv_candidates(config)
            if not candidates:
                run_state["failureCount"] += 1
                run_state["repairQueuedCount"] += 1
                errors.append(
                    self._handle_run_failure(
                        run_id=normalized_run_id,
                        step=exc.step,
                        error_code=exc.code,
                        error_message=str(exc),
                        hard_block=False,
                    )
                )
                return self._finalize_run(run_state, published_ids=[], errors=errors)
            run_state["failureCount"] += 1
            run_state["repairQueuedCount"] += 1
            errors.append(
                self._handle_run_failure(
                    run_id=normalized_run_id,
                    step=exc.step,
                    error_code=exc.code,
                    error_message=str(exc),
                    hard_block=False,
                    context={
                        "fallback": "papers_cache",
                        "fallbackCandidateCount": len(candidates),
                    },
                )
            )
        except Exception as exc:
            hard_block = _is_hard_block_error(type(exc).__name__, str(exc))
            candidates = [] if hard_block else self._cached_arxiv_candidates(config)
            if candidates:
                run_state["failureCount"] += 1
                run_state["repairQueuedCount"] += 1
                errors.append(
                    self._handle_run_failure(
                        run_id=normalized_run_id,
                        step="arxiv_fetch",
                        error_code=type(exc).__name__,
                        error_message=str(exc),
                        hard_block=False,
                        context={
                            "fallback": "papers_cache",
                            "fallbackCandidateCount": len(candidates),
                        },
                    )
                )
            else:
                if hard_block:
                    run_state["blockedCount"] += 1
                else:
                    run_state["failureCount"] += 1
                    run_state["repairQueuedCount"] += 1
                errors.append(
                    self._handle_run_failure(
                        run_id=normalized_run_id,
                        step="arxiv_fetch",
                        error_code=type(exc).__name__,
                        error_message=str(exc),
                        hard_block=hard_block,
                    )
                )
                return self._finalize_run(run_state, published_ids=[], errors=errors)
        run_state["candidateCount"] = len(candidates)
        published_ids: list[str] = []
        self.state.record_run(_progress_run_state(run_state, published_ids=published_ids, errors=errors))

        for candidate in candidates[: config.candidate_limit]:
            run_state["processedCount"] += 1
            try:
                outcome = self._process_candidate(candidate, run_id=normalized_run_id, config=config)
            except PaperIngestHardBlock as exc:
                run_state["blockedCount"] += 1
                blocked = self._handle_failure(
                    run_id=normalized_run_id,
                    candidate=candidate,
                    step=exc.step,
                    error_code=exc.code,
                    error_message=str(exc),
                    hard_block=True,
                )
                errors.append(blocked)
                self.state.record_run(_progress_run_state(run_state, published_ids=published_ids, errors=errors))
                continue
            except PaperIngestError as exc:
                run_state["failureCount"] += 1
                queued = self._handle_failure(
                    run_id=normalized_run_id,
                    candidate=candidate,
                    step=exc.step,
                    error_code=exc.code,
                    error_message=str(exc),
                    hard_block=False,
                )
                run_state["repairQueuedCount"] += 1
                errors.append(queued)
                self.state.record_run(_progress_run_state(run_state, published_ids=published_ids, errors=errors))
                continue
            except Exception as exc:
                run_state["failureCount"] += 1
                queued = self._handle_failure(
                    run_id=normalized_run_id,
                    candidate=candidate,
                    step="unknown",
                    error_code=type(exc).__name__,
                    error_message=str(exc),
                    hard_block=_is_hard_block_error(type(exc).__name__, str(exc)),
                )
                if queued.get("queue") == "manual_blocked":
                    run_state["blockedCount"] += 1
                else:
                    run_state["repairQueuedCount"] += 1
                errors.append(queued)
                self.state.record_run(_progress_run_state(run_state, published_ids=published_ids, errors=errors))
                continue

            if outcome["status"] == "published":
                run_state["publishedCount"] += 1
                published_ids.append(str(outcome["paperId"]))
                if outcome.get("citationFailureQueue") == "manual_blocked":
                    run_state["blockedCount"] += 1
                elif outcome.get("citationFailureQueue") == "agent_repair":
                    run_state["repairQueuedCount"] += 1
            elif outcome["status"] == "skipped_no_github":
                run_state["skippedNoGithubCount"] += 1
            elif outcome["status"] == "skipped_low_stars":
                run_state["skippedLowStarsCount"] += 1
            elif outcome["status"] == "repair_queued":
                run_state["repairQueuedCount"] += 1
            self.state.record_run(_progress_run_state(run_state, published_ids=published_ids, errors=errors))

        return self._finalize_run(run_state, published_ids=published_ids, errors=errors)

    def backfill_published_classification(
        self,
        *,
        limit: int | None = None,
        batch_size: int = 25,
        run_id: str | None = None,
        config: PaperIngestConfig | None = None,
    ) -> PaperClassificationBackfillResult:
        resolved_config = config or self.config
        started = self.clock()
        normalized_run_id = run_id or f"paper-classification-backfill-{started.strftime('%Y%m%d%H%M%S')}"
        max_items = _positive_int(limit)
        flush_batch_size = _positive_int(batch_size) or 25
        cache = self._read_paper_cache()
        papers = [dict(item) for item in _sequence(cache.get("papers")) if isinstance(item, Mapping)]
        next_papers: list[Mapping[str, Any]] = [dict(item) for item in papers]
        scanned_count = 0
        updated_count = 0
        skipped_count = 0
        repair_queued_count = 0
        blocked_count = 0
        updated_ids: list[str] = []
        errors: list[Mapping[str, Any]] = []

        def flush_cache() -> None:
            cache.update(
                {
                    "source": _optional_text(cache.get("source")) or "papers_ingest_github_arxiv_daily",
                    "collectedAt": _iso(self.clock()),
                    "papers": next_papers,
                }
            )
            self._write_paper_cache(cache)

        dirty_since_flush = 0
        for index, paper in enumerate(next_papers):
            if paper.get("isPublished") is False or not _paper_needs_taxonomy_backfill(paper):
                skipped_count += 1
                continue
            if max_items is not None and scanned_count >= max_items:
                continue

            scanned_count += 1
            candidate = _candidate_from_cached_paper(paper, fetched_at=self.clock())
            if candidate is None:
                skipped_count += 1
                continue
            paper_id = _candidate_paper_id(candidate)
            repo_url = _optional_text(paper.get("repoUrl")) or _optional_text(candidate.metadata.get("repo_url")) or ""
            github_stars = _positive_int(paper.get("githubStars") or candidate.metadata.get("github_stars")) or 0
            cached_sections = _cached_paper_sections(paper, paper_id, self.text_extraction_repository)
            full_text = _join_paper_text(paper, cached_sections)
            backfill_text_source = "text_extraction" if cached_sections else "summary"

            try:
                if backfill_text_source == "summary":
                    try:
                        pdf_url = _candidate_pdf_url(candidate) or ""
                        extraction = self._extract_pdf(
                            candidate,
                            paper_id=paper_id,
                            pdf_url=pdf_url,
                            config=resolved_config,
                        )
                        source_hash = _source_hash(candidate, pdf_url=pdf_url, repo_url=repo_url)
                        full_text_hash = hashlib.sha256(extraction.full_text.encode("utf-8")).hexdigest()[:16]
                        cached_at = _iso(self.clock())
                        self.text_extraction_repository.write_sections(
                            paper_id,
                            source_hash,
                            extraction.sections,
                            cached_at=cached_at,
                            pdf_url=pdf_url,
                            full_text_hash=full_text_hash,
                        )
                        full_text = _join_paper_text(paper, extraction.sections, fallback_text=extraction.full_text)
                        backfill_text_source = "pdf_extract"
                    except PaperIngestError as exc:
                        repair_queued_count += 1
                        errors.append(
                            self._handle_failure(
                                run_id=normalized_run_id,
                                candidate=candidate,
                                step=exc.step,
                                error_code=exc.code,
                                error_message=str(exc),
                                hard_block=False,
                                context={"mode": "classification_backfill", "fallback": "summary"},
                            )
                        )
                        if dirty_since_flush:
                            flush_cache()
                            dirty_since_flush = 0
                classification = self._classify_paper(
                    candidate,
                    full_text=full_text,
                    repo_url=repo_url,
                    github_stars=github_stars,
                    config=resolved_config,
                    run_id=normalized_run_id,
                    paper_id=paper_id,
                    page_sections=cached_sections,
                )
                taxonomy = self._normalize_classification(
                    classification,
                    config=resolved_config,
                    run_id=normalized_run_id,
                    paper_id=paper_id,
                )
                low_confidence_items = taxonomy.get("lowConfidenceItems") or []
                if low_confidence_items:
                    repair_queued_count += 1
                    errors.append(
                        self._handle_failure(
                            run_id=normalized_run_id,
                            candidate=candidate,
                            step="classify",
                            error_code="classification_low_confidence",
                            error_message="classification included low confidence taxonomy entries during backfill",
                            hard_block=False,
                            context={"lowConfidenceItems": low_confidence_items, "mode": "classification_backfill"},
                        )
                    )
                    if dirty_since_flush:
                        flush_cache()
                        dirty_since_flush = 0
                if not taxonomy.get("taskRefs") or not taxonomy.get("methodRefs"):
                    raise PaperIngestError(
                        "classification backfill did not produce publishable tasks and methods",
                        code="classification_empty",
                        step="classify",
                    )
            except PaperIngestHardBlock as exc:
                blocked_count += 1
                errors.append(
                    self._handle_failure(
                        run_id=normalized_run_id,
                        candidate=candidate,
                        step=exc.step,
                        error_code=exc.code,
                        error_message=str(exc),
                        hard_block=True,
                        context={"mode": "classification_backfill"},
                    )
                )
                if dirty_since_flush:
                    flush_cache()
                    dirty_since_flush = 0
                continue
            except PaperIngestError as exc:
                repair_queued_count += 1
                errors.append(
                    self._handle_failure(
                        run_id=normalized_run_id,
                        candidate=candidate,
                        step=exc.step,
                        error_code=exc.code,
                        error_message=str(exc),
                        hard_block=False,
                        context={"mode": "classification_backfill"},
                    )
                )
                if dirty_since_flush:
                    flush_cache()
                    dirty_since_flush = 0
                continue
            except Exception as exc:
                queued = self._handle_failure(
                    run_id=normalized_run_id,
                    candidate=candidate,
                    step="unknown",
                    error_code=type(exc).__name__,
                    error_message=str(exc),
                    hard_block=_is_hard_block_error(type(exc).__name__, str(exc)),
                    context={"mode": "classification_backfill"},
                )
                if queued.get("queue") == "manual_blocked":
                    blocked_count += 1
                else:
                    repair_queued_count += 1
                errors.append(queued)
                if dirty_since_flush:
                    flush_cache()
                    dirty_since_flush = 0
                continue

            updated = _deep_merge(
                paper,
                {
                    "taskRefs": taxonomy.get("taskRefs") or [],
                    "methodRefs": taxonomy.get("methodRefs") or [],
                    "benchmarks": taxonomy.get("benchmarks") or [],
                    "classification": dict(_classification_record(taxonomy=taxonomy, classification=classification))
                    | {
                        "backfillTextSource": backfill_text_source,
                        "fullTextAvailable": backfill_text_source in {"text_extraction", "pdf_extract"},
                    },
                },
            )
            next_papers[index] = updated
            updated_count += 1
            updated_ids.append(_optional_text(updated.get("id")) or paper_id)
            dirty_since_flush += 1
            if dirty_since_flush >= flush_batch_size:
                flush_cache()
                dirty_since_flush = 0

        if dirty_since_flush:
            flush_cache()
        finished = self.clock()
        return PaperClassificationBackfillResult(
            run_id=normalized_run_id,
            started_at=_iso(started),
            finished_at=_iso(finished),
            batch_size=flush_batch_size,
            scanned_count=scanned_count,
            updated_count=updated_count,
            skipped_count=skipped_count,
            repair_queued_count=repair_queued_count,
            blocked_count=blocked_count,
            updated_paper_ids=tuple(updated_ids),
            errors=tuple(errors),
        )

    def backfill_published_citations(
        self,
        *,
        limit: int | None = None,
        batch_size: int = DEFAULT_OPENALEX_BATCH_SIZE,
        run_id: str | None = None,
    ) -> PaperCitationBackfillResult:
        started = self.clock()
        normalized_run_id = run_id or f"paper-citation-backfill-{started.strftime('%Y%m%d%H%M%S')}"
        max_items = _positive_int(limit)
        flush_batch_size = min(_positive_int(batch_size) or DEFAULT_OPENALEX_BATCH_SIZE, 200)
        cache = self._read_paper_cache()
        papers = [dict(item) for item in _sequence(cache.get("papers")) if isinstance(item, Mapping)]
        next_papers: list[Mapping[str, Any]] = [dict(item) for item in papers]
        scanned_count = 0
        updated_count = 0
        skipped_count = 0
        repair_queued_count = 0
        blocked_count = 0
        updated_ids: list[str] = []
        errors: list[Mapping[str, Any]] = []
        dirty_since_flush = 0

        def flush_cache() -> None:
            cache.update(
                {
                    "source": _optional_text(cache.get("source")) or "papers_ingest_github_arxiv_daily",
                    "collectedAt": _iso(self.clock()),
                    "papers": next_papers,
                }
            )
            self._write_paper_cache(cache)

        def process_batch(batch: Sequence[tuple[int, Mapping[str, Any], str, RawSourceItem]]) -> bool:
            nonlocal updated_count, repair_queued_count, blocked_count, dirty_since_flush
            if not batch:
                return True
            try:
                citation_by_doi = self.citation_client.fetch_by_dois([doi for _, _, doi, _ in batch])
            except PaperIngestHardBlock as exc:
                blocked_count += 1
                errors.append(
                    self._handle_run_failure(
                        run_id=normalized_run_id,
                        step=exc.step,
                        error_code=exc.code,
                        error_message=str(exc),
                        hard_block=True,
                        context={"mode": "citation_backfill", "doiCount": len(batch)},
                    )
                )
                if dirty_since_flush:
                    flush_cache()
                    dirty_since_flush = 0
                return False
            except PaperIngestError as exc:
                repair_queued_count += 1
                errors.append(
                    self._handle_run_failure(
                        run_id=normalized_run_id,
                        step=exc.step,
                        error_code=exc.code,
                        error_message=str(exc),
                        hard_block=False,
                        context={"mode": "citation_backfill", "doiCount": len(batch)},
                    )
                )
                if dirty_since_flush:
                    flush_cache()
                    dirty_since_flush = 0
                return False

            fetched_at = _iso(self.clock())
            for index, paper, doi, candidate in batch:
                citation = citation_by_doi.get(doi)
                if citation is None:
                    repair_queued_count += 1
                    errors.append(
                        self._handle_failure(
                            run_id=normalized_run_id,
                            candidate=candidate,
                            step="citation_fetch",
                            error_code="openalex_citation_not_found",
                            error_message=f"OpenAlex did not return a work for DOI {doi}",
                            hard_block=False,
                            context={"mode": "citation_backfill", "doi": doi},
                        )
                    )
                    continue
                if not _openalex_title_matches_paper(paper, citation):
                    repair_queued_count += 1
                    errors.append(
                        self._handle_failure(
                            run_id=normalized_run_id,
                            candidate=candidate,
                            step="citation_fetch",
                            error_code="openalex_title_mismatch",
                            error_message="OpenAlex DOI result title did not match the cached paper title",
                            hard_block=False,
                            context={
                                "mode": "citation_backfill",
                                "doi": doi,
                                "openAlexId": citation.openalex_id,
                                "openAlexTitle": citation.display_name,
                            },
                        )
                    )
                    continue
                updated = _deep_merge(paper, citation.to_cache_payload(fetched_at=fetched_at))
                next_papers[index] = updated
                updated_count += 1
                updated_ids.append(_optional_text(updated.get("id")) or _candidate_paper_id(candidate))
                dirty_since_flush += 1
                if dirty_since_flush >= flush_batch_size:
                    flush_cache()
                    dirty_since_flush = 0
            return True

        batch: list[tuple[int, Mapping[str, Any], str, RawSourceItem]] = []
        for index, paper in enumerate(next_papers):
            if paper.get("isPublished") is False or not _paper_needs_citation_backfill(paper):
                skipped_count += 1
                continue
            if max_items is not None and scanned_count >= max_items:
                continue
            doi = _citation_doi_for_record(paper)
            if not doi:
                skipped_count += 1
                continue
            candidate = _candidate_from_cached_paper(paper, fetched_at=self.clock())
            if candidate is None:
                skipped_count += 1
                continue
            scanned_count += 1
            batch.append((index, paper, doi, candidate))
            if len(batch) >= flush_batch_size:
                if not process_batch(batch):
                    batch = []
                    break
                batch = []

        if batch:
            process_batch(batch)
        if dirty_since_flush:
            flush_cache()
        finished = self.clock()
        return PaperCitationBackfillResult(
            run_id=normalized_run_id,
            started_at=_iso(started),
            finished_at=_iso(finished),
            batch_size=flush_batch_size,
            scanned_count=scanned_count,
            updated_count=updated_count,
            skipped_count=skipped_count,
            repair_queued_count=repair_queued_count,
            blocked_count=blocked_count,
            updated_paper_ids=tuple(updated_ids),
            errors=tuple(errors),
        )

    def get_ops_state(self, *, limit: int = 20) -> Mapping[str, Any]:
        self.state.reclassify_soft_blocked_items(now=self.clock)
        return sanitize_public_payload(
            {
                "runs": self.state.list_runs(limit=limit),
                "repairQueue": self.state.list_repair_items(limit=limit),
                "blockedItems": self.state.list_blocked_items(limit=limit),
                "taxonomyEvents": self.state.list_taxonomy_events(limit=limit),
                "promptMemory": self.state.list_prompt_memory(limit=limit),
                "config": {
                    "candidateLimit": self.config.candidate_limit,
                    "minGithubStars": self.config.min_github_stars,
                    "autoTaxonomyConfidence": self.config.auto_taxonomy_confidence,
                    "arxivQuery": self.config.arxiv_query,
                    "classifierModelRoute": self.config.classifier_model_route,
                },
            }
        )

    def get_thumbnail_path(self, file_name: str) -> Path | None:
        if not _is_safe_file_name(file_name):
            return None
        path = (self.state.thumbnail_dir / file_name).resolve()
        root = self.state.thumbnail_dir.resolve()
        if root not in path.parents:
            return None
        return path if path.exists() and path.is_file() else None

    def record_background_failure(
        self,
        *,
        run_id: str,
        task_type: str,
        step: str,
        error: Exception,
    ) -> None:
        now = self.clock()
        run_state = _new_run_state(run_id, started=now, config=self.config)
        run_state.update(
            {
                "status": "failed",
                "finishedAt": _iso(now),
                "failureCount": 1,
                "errors": [
                    {
                        "runId": run_id,
                        "taskType": task_type,
                        "step": step,
                        "errorCode": type(error).__name__,
                        "errorMessage": str(error),
                        "retryable": True,
                        "createdAt": _iso(now),
                    }
                ],
            }
        )
        self.state.record_run(run_state)

    def _fetch_candidates(self, config: PaperIngestConfig) -> list[RawSourceItem]:
        if self.source_service is not None:
            result = self.source_service.fetch_arxiv(query=config.arxiv_query, limit=config.candidate_limit)
            items = list(getattr(result, "items", []) or [])
            errors = getattr(result, "errors", None) or []
        else:
            source = SourceDefinition(
                source_id="arxiv",
                name="arXiv",
                source_type="arxiv",
                url=ARXIV_API_URL,
                reliability="high",
                authority_score=0.95,
                topics=["papers", "research"],
                language="en",
                metadata={"query": config.arxiv_query},
                respect_robots=False,
            )
            items, errors = self.arxiv_connector.fetch(
                source,
                query=config.arxiv_query,
                limit=config.candidate_limit,
            )
        if errors:
            first_error = errors[0]
            error_payload = first_error.to_dict() if hasattr(first_error, "to_dict") else {}
            code = str(error_payload.get("error_type") or error_payload.get("code") or "arxiv_fetch_failed")
            message = str(error_payload.get("message") or error_payload.get("error_message") or code)
            if _is_hard_block_error(code, message):
                raise PaperIngestHardBlock(message, code=code, step="arxiv_fetch", retryable=False)
            raise PaperIngestError(message, code=code, step="arxiv_fetch")
        return _dedupe_candidates(items)

    def _cached_arxiv_candidates(self, config: PaperIngestConfig) -> list[RawSourceItem]:
        payload = read_json_object(self.papers_data_path, default={})
        papers = payload.get("papers") if isinstance(payload, Mapping) else None
        if not isinstance(papers, Sequence):
            return []
        candidates = [
            candidate
            for paper in papers
            if isinstance(paper, Mapping)
            for candidate in [_candidate_from_cached_paper(paper, fetched_at=self.clock())]
            if candidate is not None
        ]
        return _dedupe_candidates(candidates)[: config.candidate_limit]

    def _process_candidate(
        self,
        candidate: RawSourceItem,
        *,
        run_id: str,
        config: PaperIngestConfig,
    ) -> Mapping[str, Any]:
        paper_id = _candidate_paper_id(candidate)
        pdf_url = _candidate_pdf_url(candidate)
        candidate_text = _candidate_search_text(candidate)
        repo_url = _extract_github_repo_url(candidate_text)
        extraction: PaperPdfExtraction | None = None

        if repo_url is None and pdf_url:
            extraction = self._extract_pdf(candidate, paper_id=paper_id, pdf_url=pdf_url, config=config)
            repo_url = _extract_github_repo_url(extraction.full_text)
        if repo_url is None:
            return {"status": "skipped_no_github", "paperId": paper_id}

        repo_url = _normalize_github_repo_url(repo_url)
        if repo_url is None:
            raise PaperIngestError("candidate contained an invalid GitHub repository URL", code="github_url_invalid", step="github_extract")

        repository = _repository_slug_from_url(repo_url)
        metadata = self._fetch_github_metadata(repository)
        if metadata.stargazers_count < config.min_github_stars:
            return {
                "status": "skipped_low_stars",
                "paperId": paper_id,
                "repoUrl": repo_url,
                "githubStars": metadata.stargazers_count,
            }

        if extraction is None:
            if not pdf_url:
                raise PaperIngestError("candidate did not include a PDF URL", code="pdf_url_missing", step="pdf_fetch")
            extraction = self._extract_pdf(candidate, paper_id=paper_id, pdf_url=pdf_url, config=config)

        classification = self._classify_paper(
            candidate,
            full_text=extraction.full_text,
            repo_url=repo_url,
            github_stars=metadata.stargazers_count,
            config=config,
            run_id=run_id,
            paper_id=paper_id,
            page_sections=extraction.sections,
        )
        taxonomy = self._normalize_classification(classification, config=config, run_id=run_id, paper_id=paper_id)
        low_confidence_items = taxonomy.get("lowConfidenceItems") or []
        if low_confidence_items:
            self._handle_failure(
                run_id=run_id,
                candidate=candidate,
                step="classify",
                error_code="classification_low_confidence",
                error_message="classification included low confidence taxonomy entries",
                hard_block=False,
                context={"lowConfidenceItems": low_confidence_items},
            )

        task_refs = taxonomy.get("taskRefs") if isinstance(taxonomy.get("taskRefs"), list) else []
        method_refs = taxonomy.get("methodRefs") if isinstance(taxonomy.get("methodRefs"), list) else []
        if not task_refs or not method_refs:
            raise PaperIngestError(
                "classification did not produce publishable tasks and methods",
                code="classification_empty",
                step="classify",
            )

        source_hash = _source_hash(candidate, pdf_url=pdf_url, repo_url=repo_url)
        cached_at = _iso(self.clock())
        full_text_hash = hashlib.sha256(extraction.full_text.encode("utf-8")).hexdigest()[:16]
        self.text_extraction_repository.write_sections(
            paper_id,
            source_hash,
            extraction.sections,
            cached_at=cached_at,
            pdf_url=pdf_url,
            full_text_hash=full_text_hash,
        )

        citation: PaperCitationMetadata | None = None
        citation_failure: Mapping[str, Any] | None = None
        try:
            citation = self._fetch_citation_metadata(candidate)
        except PaperIngestHardBlock as exc:
            citation_failure = self._handle_failure(
                run_id=run_id,
                candidate=candidate,
                step=exc.step,
                error_code=exc.code,
                error_message=str(exc),
                hard_block=True,
                context={"mode": "ingest", "nonBlocking": True},
            )
        except PaperIngestError as exc:
            citation_failure = self._handle_failure(
                run_id=run_id,
                candidate=candidate,
                step=exc.step,
                error_code=exc.code,
                error_message=str(exc),
                hard_block=False,
                context={"mode": "ingest", "nonBlocking": True},
            )

        thumbnail_url = _thumbnail_url(extraction.thumbnail_path)
        paper_payload = _paper_payload_from_ingest(
            candidate,
            paper_id=paper_id,
            pdf_url=pdf_url,
            repo_url=repo_url,
            github=metadata,
            thumbnail_url=thumbnail_url,
            citation=citation,
            taxonomy=taxonomy,
            classification=classification,
            run_id=run_id,
            collected_at=cached_at,
        )
        self._publish_paper(paper_payload, collected_at=cached_at)
        return {
            "status": "published",
            "paperId": paper_id,
            "citationFailureQueue": citation_failure.get("queue") if citation_failure else None,
        }

    def _extract_pdf(
        self,
        candidate: RawSourceItem,
        *,
        paper_id: str,
        pdf_url: str,
        config: PaperIngestConfig,
    ) -> PaperPdfExtraction:
        normalized_pdf_url = _normalize_pdf_url(pdf_url)
        if not normalized_pdf_url:
            raise PaperIngestError("PDF URL could not be normalized", code="pdf_url_invalid", step="pdf_fetch")
        try:
            pdf_bytes = self.pdf_fetcher(normalized_pdf_url, config.pdf_max_bytes)
            thumbnail_path = self.state.thumbnail_dir / f"{_safe_file_key(paper_id)}.png"
            return self.pdf_processor.extract(
                pdf_bytes,
                paper_id=paper_id,
                pdf_url=normalized_pdf_url,
                thumbnail_path=thumbnail_path,
            )
        except PaperIngestError:
            raise
        except (HTTPError, URLError, OSError, ValueError) as exc:
            raise PaperIngestError(str(exc), code="pdf_fetch_failed", step="pdf_fetch") from exc

    def _fetch_github_metadata(self, repository: str) -> GithubRepositoryMetadata:
        source = SourceDefinition(
            source_id="github",
            name="GitHub",
            source_type="github",
            url=GITHUB_API_URL,
            reliability="high",
            authority_score=0.9,
            topics=["github", "repository"],
            metadata={"repository": repository},
            respect_robots=False,
        )
        metadata, errors = self.github_connector.fetch_repository_metadata(source, repository=repository)
        if errors:
            first_error = errors[0]
            payload = first_error.to_dict() if hasattr(first_error, "to_dict") else {}
            code = str(payload.get("error_type") or payload.get("code") or "github_metadata_failed")
            message = str(payload.get("message") or payload.get("error_message") or code)
            if _is_hard_block_error(code, message):
                raise PaperIngestHardBlock(message, code=code, step="github_verify", retryable=False)
            raise PaperIngestError(message, code=code, step="github_verify")
        if metadata is None:
            raise PaperIngestError("GitHub repository metadata was empty", code="github_metadata_empty", step="github_verify")
        if metadata.archived or metadata.disabled:
            raise PaperIngestError("GitHub repository is archived or disabled", code="github_repo_inactive", step="github_verify")
        return metadata

    def _fetch_citation_metadata(self, candidate: RawSourceItem) -> PaperCitationMetadata | None:
        doi = _citation_doi_for_candidate(candidate)
        if not doi:
            return None
        citation_by_doi = self.citation_client.fetch_by_dois([doi])
        citation = citation_by_doi.get(doi)
        if citation is None:
            raise PaperIngestError(
                f"OpenAlex did not return a work for DOI {doi}",
                code="openalex_citation_not_found",
                step="citation_fetch",
            )
        if not _openalex_title_matches_candidate(candidate, citation):
            raise PaperIngestError(
                "OpenAlex DOI result title did not match the candidate paper title",
                code="openalex_title_mismatch",
                step="citation_fetch",
            )
        return citation

    def _classify_paper(
        self,
        candidate: RawSourceItem,
        *,
        full_text: str,
        repo_url: str,
        github_stars: int,
        config: PaperIngestConfig,
        run_id: str | None = None,
        paper_id: str | None = None,
        page_sections: Sequence[Mapping[str, Any]] = (),
    ) -> Mapping[str, Any]:
        try:
            return self._classify_paper_with_agent_analysis(
                candidate,
                full_text=full_text,
                repo_url=repo_url,
                github_stars=github_stars,
                run_id=run_id,
                paper_id=paper_id,
                page_sections=page_sections,
            )
        except Exception as exc:
            self._record_agent_analysis_fallback(
                candidate,
                error=exc,
                run_id=run_id,
                paper_id=paper_id,
                fallback_enabled=config.use_legacy_classifier_fallback,
            )
            if not config.use_legacy_classifier_fallback:
                if isinstance(exc, PaperIngestError):
                    raise
                raise PaperIngestError(
                    f"paper agent analysis failed and legacy fallback is disabled: {exc}",
                    code="agent_analysis_failed",
                    step="classify",
                ) from exc
            legacy_profile = dict(
                self._classify_paper_with_llm(
                    candidate,
                    full_text=full_text,
                    repo_url=repo_url,
                    github_stars=github_stars,
                    config=config,
                )
            )
            return _mark_legacy_classifier_fallback(legacy_profile, error=exc)

    def _record_agent_analysis_fallback(
        self,
        candidate: RawSourceItem,
        *,
        error: Exception,
        run_id: str | None,
        paper_id: str | None,
        fallback_enabled: bool,
    ) -> None:
        self.state.record_prompt_memory(
            {
                "memoryId": _stable_id(
                    "prompt-memory",
                    paper_id or _candidate_paper_id(candidate),
                    run_id or "agent-analysis",
                    "agent_analysis_fallback",
                ),
                "createdAt": _iso(self.clock()),
                "failureType": "agent_analysis_failed",
                "inputFeature": candidate.title,
                "rootCause": str(error),
                "repairAction": "fallback_to_legacy_classifier" if fallback_enabled else "manual_review_agent_analysis",
                "result": "legacy_fallback" if fallback_enabled else "blocked",
                "legacy": fallback_enabled,
            }
        )

    def _classify_paper_with_agent_analysis(
        self,
        candidate: RawSourceItem,
        *,
        full_text: str,
        repo_url: str,
        github_stars: int,
        run_id: str | None,
        paper_id: str | None,
        page_sections: Sequence[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        resolved_paper_id = paper_id or _candidate_paper_id(candidate)
        analysis = self.paper_analysis_orchestrator.analyze_paper(
            PaperAnalysisRequest(
                paper_id=resolved_paper_id,
                run_id=run_id or f"paper-analysis-{_stable_id('run', resolved_paper_id)[:12]}",
                title=candidate.title,
                abstract=candidate.summary or "",
                full_text=full_text,
                page_sections=tuple(page_sections),
                repo_url=repo_url,
                github_stars=github_stars,
                metadata={
                    "source": candidate.source_id,
                    "sourceItemId": candidate.source_item_id,
                    "tags": list(candidate.tags),
                },
            )
        )
        profile = dict(analysis.final_profile)
        if not profile.get("taskRefs") or not profile.get("methodRefs"):
            raise PaperIngestError(
                "agent analysis did not produce publishable tasks and methods",
                code="agent_analysis_empty",
                step="classify",
            )
        return profile

    def _classify_paper_with_llm(
        self,
        candidate: RawSourceItem,
        *,
        full_text: str,
        repo_url: str,
        github_stars: int,
        config: PaperIngestConfig,
    ) -> Mapping[str, Any]:
        taxonomy = self._taxonomy_context()
        memory = self.state.relevant_prompt_memory(
            [
                candidate.title,
                candidate.summary or "",
                " ".join(candidate.tags),
            ]
        )
        request = _classification_request(
            candidate,
            full_text=full_text,
            repo_url=repo_url,
            github_stars=github_stars,
            taxonomy=taxonomy,
            prompt_memory=memory,
            max_chars=config.classifier_max_chars,
        )
        try:
            client = self.llm_client_factory(config.classifier_model_route)
            response = client.complete(request)
        except (LLMConfigurationError, LLMProviderError) as exc:
            if _is_hard_block_error(type(exc).__name__, str(exc)):
                raise PaperIngestHardBlock(str(exc), code="classifier_unavailable", step="classify", retryable=False) from exc
            raise PaperIngestError(str(exc), code="classifier_unavailable", step="classify") from exc
        except (RuntimeError, OSError, ValueError) as exc:
            if _is_hard_block_error(type(exc).__name__, str(exc)):
                raise PaperIngestHardBlock(str(exc), code="classifier_hard_blocked", step="classify", retryable=False) from exc
            raise PaperIngestError(str(exc), code="classifier_failed", step="classify") from exc

        content = str(getattr(response, "content", "") or "")
        payload, repaired = _parse_json_object(content)
        if not payload:
            raise PaperIngestError("classifier returned invalid JSON", code="classifier_json_invalid", step="classify")
        if repaired:
            self.state.record_prompt_memory(
                {
                    "memoryId": _stable_id("prompt-memory", candidate.title, "classifier_json_repaired"),
                    "createdAt": _iso(self.clock()),
                    "failureType": "classifier_json_invalid",
                    "inputFeature": candidate.title,
                    "rootCause": "model wrapped JSON with non-JSON text",
                    "repairAction": "extracted first JSON object from response",
                    "result": "repaired",
                }
            )
        return payload

    def _normalize_classification(
        self,
        payload: Mapping[str, Any],
        *,
        config: PaperIngestConfig,
        run_id: str,
        paper_id: str,
    ) -> Mapping[str, Any]:
        taxonomy = self._taxonomy_context()
        low_confidence: list[Mapping[str, Any]] = [
            dict(item) for item in _sequence(payload.get("lowConfidenceItems")) if isinstance(item, Mapping)
        ]
        task_value = payload.get("taskRefs") or payload.get("tasks")
        method_value = payload.get("methodRefs") or payload.get("methods")
        method_collections = taxonomy.get("methodCollections")
        method_collection_names = (
            tuple(str(item) for item in method_collections)
            if isinstance(method_collections, Sequence) and not isinstance(method_collections, (str, bytes))
            else load_pwc_method_collections()
        )
        primary_task_group = normalize_ai_task_group(
            payload.get("primaryTaskGroup") or payload.get("primary_task_group")
        ) or _first_valid_task_group(task_value)
        if primary_task_group is None:
            low_confidence.append(
                {
                    "kind": "task",
                    "slug": None,
                    "name": "Primary task group",
                    "confidence": _float(payload.get("confidence"), default=0.0),
                    "evidence": _optional_text(payload.get("evidenceSummary") or payload.get("evidence_summary")),
                    "reason": "missing_or_invalid_primary_task_group",
                    "allowedValues": list(AI_TASK_GROUPS),
                    "action": "agent_repair_retry",
                }
            )
        secondary_task_groups, invalid_secondary_groups = _normalize_secondary_task_groups(
            payload.get("secondaryTaskGroups") or payload.get("secondary_task_groups")
        )
        classification_confidence = _float(payload.get("confidence"), default=0.0)
        for invalid_group in invalid_secondary_groups:
            low_confidence.append(
                {
                    "kind": "task",
                    "slug": _slugify(invalid_group),
                    "name": invalid_group,
                    "confidence": classification_confidence,
                    "reason": "invalid_secondary_task_group",
                    "allowedValues": list(AI_TASK_GROUPS),
                    "action": "agent_repair_retry",
                }
            )
        task_refs = self._normalize_refs(
            task_value,
            kind="task",
            existing=taxonomy["tasksBySlug"],
            confidence_threshold=config.auto_taxonomy_confidence,
            run_id=run_id,
            paper_id=paper_id,
            low_confidence=low_confidence,
            default_task_group=primary_task_group,
            method_collections=method_collection_names,
            default_confidence=classification_confidence,
        )
        method_refs = self._normalize_refs(
            method_value,
            kind="method",
            existing=taxonomy["methodsBySlug"],
            confidence_threshold=config.auto_taxonomy_confidence,
            run_id=run_id,
            paper_id=paper_id,
            low_confidence=low_confidence,
            default_task_group=primary_task_group,
            method_collections=method_collection_names,
            default_confidence=classification_confidence,
        )
        benchmarks = self._normalize_benchmarks(
            payload.get("benchmarks"),
            confidence_threshold=config.auto_taxonomy_confidence,
            run_id=run_id,
            paper_id=paper_id,
            low_confidence=low_confidence,
            default_confidence=classification_confidence,
        )
        return sanitize_public_payload(
            {
                "primaryTaskGroup": primary_task_group,
                "secondaryTaskGroups": secondary_task_groups,
                "taskRefs": task_refs,
                "methodRefs": method_refs,
                "benchmarks": benchmarks,
                "lowConfidenceItems": low_confidence,
                "confidence": _float(payload.get("confidence")),
                "evidenceSummary": _optional_text(payload.get("evidenceSummary") or payload.get("evidence_summary")),
            }
        )

    def _normalize_refs(
        self,
        value: Any,
            *,
            kind: str,
            existing: Mapping[str, Mapping[str, Any]],
            confidence_threshold: float,
            run_id: str,
            paper_id: str,
            low_confidence: list[Mapping[str, Any]],
            default_task_group: str | None,
            method_collections: Sequence[str],
            default_confidence: float,
    ) -> list[Mapping[str, Any]]:
        refs: list[Mapping[str, Any]] = []
        for item in _sequence(value):
            if isinstance(item, str):
                item = {"name": item}
            if not isinstance(item, Mapping):
                continue
            name = _optional_text(item.get("name")) or _optional_text(item.get("label"))
            slug = _slugify(_optional_text(item.get("slug")) or name)
            if not name or not slug:
                continue
            confidence = _float(item.get("confidence"), default=1.0 if slug in existing else default_confidence)
            evidence = _optional_text(item.get("evidence") or item.get("evidenceSummary"))
            ref_extra: dict[str, Any] = {}
            if kind == "task":
                group = normalize_ai_task_group(item.get("group") or item.get("taskGroup") or default_task_group)
                if group is None:
                    low_confidence.append(
                        {
                            "kind": kind,
                            "slug": slug,
                            "name": name,
                            "confidence": confidence,
                            "evidence": evidence,
                            "reason": "missing_or_invalid_task_group",
                            "allowedValues": list(AI_TASK_GROUPS),
                            "action": "agent_repair_retry",
                        }
                    )
                    continue
                ref_extra["group"] = group
            if kind == "method":
                area = normalize_method_collection(
                    item.get("area") or item.get("collection") or item.get("methodCollection") or name,
                    collections=method_collections,
                )
                if area is None:
                    low_confidence.append(
                        {
                            "kind": kind,
                            "slug": slug,
                            "name": name,
                            "confidence": confidence,
                            "evidence": evidence,
                            "reason": "missing_or_invalid_method_collection",
                            "allowedValues": list(method_collections),
                            "action": "agent_repair_retry",
                        }
                    )
                    continue
                ref_extra["area"] = area
            if slug in existing:
                existing_ref = dict(existing[slug]) | ref_extra
                refs.append(_public_ref(existing_ref, confidence=confidence, evidence=evidence))
                continue
            if confidence >= confidence_threshold:
                ref = {
                    "id": _optional_text(item.get("id")) or f"{kind}-{slug}",
                    "slug": slug,
                    "name": name,
                } | ref_extra
                self.state.upsert_taxonomy_ref(kind, ref)
                self.state.record_taxonomy_event(
                    {
                        "eventId": _stable_id("taxonomy", run_id, paper_id, kind, slug),
                        "runId": run_id,
                        "paperId": paper_id,
                        "kind": kind,
                        "slug": slug,
                        "name": name,
                        **ref_extra,
                        "confidence": confidence,
                        "evidence": evidence,
                        "action": "auto_published",
                        "createdAt": _iso(self.clock()),
                    }
                )
                refs.append(_public_ref(ref, confidence=confidence, evidence=evidence))
                continue
            low_confidence.append(
                {
                    "kind": kind,
                    "slug": slug,
                    "name": name,
                    "confidence": confidence,
                    "evidence": evidence,
                    "action": "agent_repair_retry",
                }
            )
        return _dedupe_refs(refs)

    def _normalize_benchmarks(
        self,
        value: Any,
        *,
            confidence_threshold: float,
            run_id: str,
            paper_id: str,
            low_confidence: list[Mapping[str, Any]],
            default_confidence: float,
    ) -> list[Mapping[str, Any]]:
        benchmarks: list[Mapping[str, Any]] = []
        for item in _sequence(value):
            if isinstance(item, str):
                item = {"name": item}
            if not isinstance(item, Mapping):
                continue
            name = _optional_text(item.get("name"))
            if not name:
                continue
            slug = _slugify(_optional_text(item.get("slug")) or name)
            confidence = _float(item.get("confidence"), default=default_confidence)
            evidence = _optional_text(item.get("evidence") or item.get("evidenceSummary"))
            category = normalize_benchmark_category(
                item.get("category") or item.get("benchmarkCategory") or item.get("benchmark_category")
            )
            metric = _optional_text(item.get("metric"))
            if category is None or not metric:
                low_confidence.append(
                    {
                        "kind": "benchmark",
                        "slug": slug,
                        "name": name,
                        "confidence": confidence,
                        "evidence": evidence,
                        "reason": "missing_or_invalid_benchmark_category_or_metric",
                        "allowedValues": list(BENCHMARK_CATEGORIES),
                        "action": "agent_repair_retry",
                    }
                )
                continue
            if confidence < confidence_threshold:
                low_confidence.append(
                    {
                        "kind": "benchmark",
                        "slug": slug,
                        "name": name,
                        "confidence": confidence,
                        "evidence": evidence,
                        "action": "agent_repair_retry",
                    }
                )
                continue
            benchmark = {
                "id": _optional_text(item.get("id")) or f"bench-{slug}",
                "name": name,
                "category": category,
                "metric": metric,
                "value": item.get("value") if item.get("value") not in (None, "", [], {}) else None,
                "taskSlug": _optional_text(item.get("taskSlug") or item.get("task_slug")),
                "url": _normalized_https_url(item.get("url")),
                "confidence": confidence,
                "evidence": evidence,
            }
            benchmarks.append({key: val for key, val in benchmark.items() if val not in (None, "", [], {})})
            self.state.record_taxonomy_event(
                {
                    "eventId": _stable_id("taxonomy", run_id, paper_id, "benchmark", slug),
                    "runId": run_id,
                    "paperId": paper_id,
                    "kind": "benchmark",
                    "slug": slug,
                    "name": name,
                    "category": category,
                    "confidence": confidence,
                    "evidence": evidence,
                    "action": "auto_published",
                    "createdAt": _iso(self.clock()),
                }
            )
        return benchmarks

    def _taxonomy_context(self) -> Mapping[str, Any]:
        cache = self._read_paper_cache()
        tasks: dict[str, Mapping[str, Any]] = {}
        methods: dict[str, Mapping[str, Any]] = {}
        for item in _sequence(cache.get("papers")):
            if not isinstance(item, Mapping) or item.get("isPublished") is False:
                continue
            for ref in _sequence(item.get("taskRefs")):
                _add_ref_to_index(tasks, ref)
            for ref in _sequence(item.get("methodRefs")):
                _add_ref_to_index(methods, ref)
        stored = self.state.read_taxonomy()
        for ref in _sequence(stored.get("tasks")):
            _add_ref_to_index(tasks, ref)
        for ref in _sequence(stored.get("methods")):
            _add_ref_to_index(methods, ref)
        method_collections = load_pwc_method_collections()
        return {
            "tasks": list(tasks.values()),
            "methods": list(methods.values()),
            "tasksBySlug": tasks,
            "methodsBySlug": methods,
            "taskGroups": list(AI_TASK_GROUPS),
            "methodCollections": list(method_collections),
            "benchmarkCategories": list(BENCHMARK_CATEGORIES),
        }

    def _publish_paper(self, paper_payload: Mapping[str, Any], *, collected_at: str) -> None:
        with locked_json_file(self.papers_data_path) as path:
            cache = self._read_paper_cache_unlocked(path)
            papers = [dict(item) for item in _sequence(cache.get("papers")) if isinstance(item, Mapping)]
            paper_id = str(paper_payload["id"])
            arxiv_id = _optional_text(paper_payload.get("arxivId"))
            merged = False
            next_papers: list[Mapping[str, Any]] = []
            for existing in papers:
                if existing.get("id") == paper_id or (arxiv_id and existing.get("arxivId") == arxiv_id):
                    next_papers.append(_deep_merge(existing, paper_payload))
                    merged = True
                else:
                    next_papers.append(existing)
            if not merged:
                next_papers.append(dict(paper_payload))
            cache.update(
                {
                    "source": "papers_ingest_github_arxiv_daily",
                    "collectedAt": collected_at,
                    "papers": next_papers,
                }
            )
            self._write_paper_cache_unlocked(path, cache)

    def _read_paper_cache(self) -> dict[str, Any]:
        with locked_json_file(self.papers_data_path) as path:
            return self._read_paper_cache_unlocked(path)

    def _read_paper_cache_unlocked(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {"source": "papers_ingest_github_arxiv_daily", "papers": []}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PaperIngestError(str(exc), code="papers_cache_invalid", step="publish") from exc
        if not isinstance(payload, Mapping):
            raise PaperIngestError("papers cache root must be an object", code="papers_cache_invalid", step="publish")
        return dict(payload)

    def _write_paper_cache(self, payload: Mapping[str, Any]) -> None:
        with locked_json_file(self.papers_data_path) as path:
            self._write_paper_cache_unlocked(path, payload)

    def _write_paper_cache_unlocked(self, path: Path, payload: Mapping[str, Any]) -> None:
        sanitized = sanitize_public_payload(dict(payload))
        write_json_object_unlocked(path, dict(sanitized) if isinstance(sanitized, Mapping) else {})

    def _handle_failure(
        self,
        *,
        run_id: str,
        candidate: RawSourceItem,
        step: str,
        error_code: str,
        error_message: str,
        hard_block: bool,
        context: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        paper_id = _candidate_paper_id(candidate)
        base = {
            "itemId": _stable_id("paper-ingest-failure", run_id, paper_id, step, error_code),
            "runId": run_id,
            "paperId": paper_id,
            "title": candidate.title,
            "step": step,
            "errorCode": error_code,
            "errorMessage": error_message,
            "createdAt": _iso(self.clock()),
            "context": sanitize_public_payload(context or {}),
        }
        if hard_block or _is_hard_block_error(error_code, error_message):
            blocked = dict(base) | {
                "queue": "manual_blocked",
                "status": "blocked",
                "reason": "credential_permission_or_account_block",
                "userActionRequired": True,
            }
            self.state.record_blocked_item(blocked)
            return blocked

        retry_at = self.clock() + timedelta(minutes=DEFAULT_REPAIR_DELAY_MINUTES)
        repair = dict(base) | {
            "queue": "agent_repair",
            "status": "queued",
            "retryAt": _iso(retry_at),
            "attemptCount": 0,
            "repairAction": _repair_action_for(error_code, step),
            "userActionRequired": False,
        }
        self.state.record_repair_item(repair)
        self.state.record_prompt_memory(
            {
                "memoryId": _stable_id("prompt-memory", paper_id, step, error_code),
                "createdAt": _iso(self.clock()),
                "failureType": error_code,
                "inputFeature": " ".join([candidate.title, candidate.summary or ""])[:500],
                "rootCause": error_message,
                "repairAction": repair["repairAction"],
                "result": "queued",
            }
        )
        return repair

    def _handle_run_failure(
        self,
        *,
        run_id: str,
        step: str,
        error_code: str,
        error_message: str,
        hard_block: bool,
        context: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        base = {
            "itemId": _stable_id("paper-ingest-run-failure", run_id, step, error_code),
            "runId": run_id,
            "paperId": None,
            "title": "Daily arXiv candidate fetch",
            "step": step,
            "errorCode": error_code,
            "errorMessage": error_message,
            "createdAt": _iso(self.clock()),
            "context": sanitize_public_payload(context or {}),
        }
        if hard_block or _is_hard_block_error(error_code, error_message):
            blocked = dict(base) | {
                "queue": "manual_blocked",
                "status": "blocked",
                "reason": "credential_permission_or_account_block",
                "userActionRequired": True,
            }
            self.state.record_blocked_item(blocked)
            return blocked

        retry_at = self.clock() + timedelta(minutes=DEFAULT_REPAIR_DELAY_MINUTES)
        repair = dict(base) | {
            "queue": "agent_repair",
            "status": "queued",
            "retryAt": _iso(retry_at),
            "attemptCount": 0,
            "repairAction": _repair_action_for(error_code, step),
            "userActionRequired": False,
        }
        self.state.record_repair_item(repair)
        self.state.record_prompt_memory(
            {
                "memoryId": _stable_id("prompt-memory", run_id, step, error_code),
                "createdAt": _iso(self.clock()),
                "failureType": error_code,
                "inputFeature": step,
                "rootCause": error_message,
                "repairAction": repair["repairAction"],
                "result": "queued",
            }
        )
        return repair

    def _finalize_run(
        self,
        run_state: dict[str, Any],
        *,
        published_ids: Sequence[str],
        errors: Sequence[Mapping[str, Any]],
    ) -> PaperIngestRunResult:
        finished = self.clock()
        status = "succeeded"
        if run_state["blockedCount"]:
            status = "blocked"
        elif run_state["failureCount"] or run_state["repairQueuedCount"]:
            status = "partial"
        run_state.update(
            {
                "status": status,
                "finishedAt": _iso(finished),
                "publishedPaperIds": list(published_ids),
                "errors": [dict(item) for item in errors],
            }
        )
        self.state.record_run(run_state)
        return _run_result_from_state(run_state)


class PaperIngestStateRepository:
    def __init__(self, state_dir: str | Path | None = None) -> None:
        self.state_dir = _state_dir(state_dir)
        self.runs_path = self.state_dir / "ingest-runs.json"
        self.repair_path = self.state_dir / "repair-queue.json"
        self.blocked_path = self.state_dir / "manual-blockers.json"
        self.prompt_memory_path = self.state_dir / "prompt-memory.json"
        self.taxonomy_events_path = self.state_dir / "taxonomy-events.json"
        self.taxonomy_path = self.state_dir / "taxonomy.json"
        self.thumbnail_dir = self.state_dir / "thumbnails"

    def record_run(self, run: Mapping[str, Any]) -> None:
        with locked_json_file(self.runs_path) as path:
            payload = _read_json_unlocked(path, default={"runs": []})
            runs = [dict(item) for item in _sequence(payload.get("runs")) if isinstance(item, Mapping)]
            runs = [dict(run), *[item for item in runs if item.get("runId") != run.get("runId")]][:100]
            _write_json_unlocked(path, {"runs": runs})

    def list_runs(self, *, limit: int = 20) -> list[Mapping[str, Any]]:
        payload = _read_json(self.runs_path, default={"runs": []})
        return [dict(item) for item in _sequence(payload.get("runs")) if isinstance(item, Mapping)][:limit]

    def record_repair_item(self, item: Mapping[str, Any]) -> None:
        self._upsert_list_item(self.repair_path, root_key="items", item=item, id_key="itemId")

    def list_repair_items(self, *, limit: int = 20) -> list[Mapping[str, Any]]:
        payload = _read_json(self.repair_path, default={"items": []})
        return [dict(item) for item in _sequence(payload.get("items")) if isinstance(item, Mapping)][:limit]

    def record_blocked_item(self, item: Mapping[str, Any]) -> None:
        self._upsert_list_item(self.blocked_path, root_key="items", item=item, id_key="itemId")

    def list_blocked_items(self, *, limit: int = 20) -> list[Mapping[str, Any]]:
        payload = _read_json(self.blocked_path, default={"items": []})
        return [dict(item) for item in _sequence(payload.get("items")) if isinstance(item, Mapping)][:limit]

    def reclassify_soft_blocked_items(self, *, now: Callable[[], datetime]) -> int:
        with locked_json_file(self.blocked_path) as path:
            blocked_payload = dict(_read_json_unlocked(path, default={"items": []}))
            blocked_items = [dict(item) for item in _sequence(blocked_payload.get("items")) if isinstance(item, Mapping)]
            if not blocked_items:
                return 0

            remaining_blocked: list[Mapping[str, Any]] = []
            reclassified: list[Mapping[str, Any]] = []
            for item in blocked_items:
                error_code = str(item.get("errorCode") or "")
                error_message = str(item.get("errorMessage") or "")
                if _is_hard_block_error(error_code, error_message):
                    remaining_blocked.append(item)
                    continue
                retry_at = now() + timedelta(minutes=DEFAULT_REPAIR_DELAY_MINUTES)
                repair = dict(item)
                repair.pop("reason", None)
                repair.update(
                    {
                        "queue": "agent_repair",
                        "status": "queued",
                        "retryAt": _iso(retry_at),
                        "attemptCount": int(repair.get("attemptCount") or 0),
                        "repairAction": _repair_action_for(error_code, str(item.get("step") or "")),
                        "userActionRequired": False,
                        "reclassifiedFrom": "manual_blocked",
                        "reclassifiedAt": _iso(now()),
                    }
                )
                reclassified.append(repair)

            if not reclassified:
                return 0
            _write_json_unlocked(path, {"items": remaining_blocked})
        for item in reclassified:
            self.record_repair_item(item)
            self.record_prompt_memory(
                {
                    "memoryId": _stable_id(
                        "prompt-memory",
                        str(item.get("runId") or ""),
                        str(item.get("paperId") or ""),
                        str(item.get("step") or ""),
                        str(item.get("errorCode") or ""),
                    ),
                    "createdAt": _iso(now()),
                    "failureType": str(item.get("errorCode") or ""),
                    "inputFeature": " ".join(
                        [
                            str(item.get("title") or ""),
                            str(item.get("step") or ""),
                        ]
                    )[:500],
                    "rootCause": str(item.get("errorMessage") or ""),
                    "repairAction": str(item.get("repairAction") or ""),
                    "result": "reclassified_from_manual_blocked",
                }
            )
        return len(reclassified)

    def record_prompt_memory(self, item: Mapping[str, Any]) -> None:
        self._upsert_list_item(self.prompt_memory_path, root_key="memories", item=item, id_key="memoryId", max_items=200)

    def list_prompt_memory(self, *, limit: int = 20) -> list[Mapping[str, Any]]:
        payload = _read_json(self.prompt_memory_path, default={"memories": []})
        return [dict(item) for item in _sequence(payload.get("memories")) if isinstance(item, Mapping)][:limit]

    def relevant_prompt_memory(self, features: Sequence[str], *, limit: int = 5) -> list[Mapping[str, Any]]:
        tokens = {token for text in features for token in re.findall(r"[a-z0-9_+-]{3,}", text.casefold())}
        memories = self.list_prompt_memory(limit=100)
        scored = []
        for item in memories:
            haystack = json.dumps(item, ensure_ascii=False).casefold()
            score = sum(1 for token in tokens if token in haystack)
            if score:
                scored.append((score, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in scored[:limit]]

    def record_taxonomy_event(self, item: Mapping[str, Any]) -> None:
        self._upsert_list_item(self.taxonomy_events_path, root_key="events", item=item, id_key="eventId", max_items=500)

    def list_taxonomy_events(self, *, limit: int = 20) -> list[Mapping[str, Any]]:
        payload = _read_json(self.taxonomy_events_path, default={"events": []})
        return [dict(item) for item in _sequence(payload.get("events")) if isinstance(item, Mapping)][:limit]

    def read_taxonomy(self) -> Mapping[str, Any]:
        return _read_json(self.taxonomy_path, default={"tasks": [], "methods": [], "benchmarks": []})

    def upsert_taxonomy_ref(self, kind: str, ref: Mapping[str, Any]) -> None:
        root_key = "tasks" if kind == "task" else "methods" if kind == "method" else "benchmarks"
        self._upsert_list_item(self.taxonomy_path, root_key=root_key, item=ref, id_key="slug", max_items=1000)

    def _upsert_list_item(
        self,
        path: Path,
        *,
        root_key: str,
        item: Mapping[str, Any],
        id_key: str,
        max_items: int = 100,
    ) -> None:
        with locked_json_file(path) as resolved:
            payload = dict(_read_json_unlocked(resolved, default={root_key: []}))
            existing = [dict(value) for value in _sequence(payload.get(root_key)) if isinstance(value, Mapping)]
            item_id = item.get(id_key)
            next_items = [dict(item), *[value for value in existing if value.get(id_key) != item_id]][:max_items]
            payload[root_key] = next_items
            _write_json_unlocked(resolved, payload)


def _classification_request(
    candidate: RawSourceItem,
    *,
    full_text: str,
    repo_url: str,
    github_stars: int,
    taxonomy: Mapping[str, Any],
    prompt_memory: Sequence[Mapping[str, Any]],
    max_chars: int,
) -> LLMRequest:
    metadata = sanitize_public_payload(candidate.metadata)
    context = {
        "title": candidate.title,
        "abstract": candidate.summary,
        "authors": candidate.authors,
        "publishedAt": _dt(candidate.published_at),
        "tags": candidate.tags,
        "url": candidate.url,
        "metadata": metadata,
        "repoUrl": repo_url,
        "githubStars": github_stars,
        "knownTasks": taxonomy.get("tasks", []),
        "knownMethods": taxonomy.get("methods", []),
        "allowedTaskGroups": task_group_options(),
        "allowedMethodAreas": method_collection_options(taxonomy.get("methodCollections")),
        "allowedBenchmarkCategories": benchmark_category_options(),
        "promptMemory": list(prompt_memory),
        "fullText": _truncate_middle(full_text, max_chars),
    }
    return LLMRequest(
        messages=[
            LLMMessage.system(
                "You classify AI research papers for NewsRoom. Read the full paper text and return strict JSON. "
                "Use only the allowedTaskGroups slugs for task grouping, allowedMethodAreas names for methodRef.area, "
                "and allowedBenchmarkCategories slugs for benchmark.category. Every paper must have exactly one "
                "primaryTaskGroup and at most two secondaryTaskGroups. Prefer existing knownTasks and knownMethods by "
                "slug when they fit; create new task/method refs only when evidence is explicit and confidence is high. "
                "Return keys: primaryTaskGroup, secondaryTaskGroups, taskRefs, methodRefs, benchmarks, confidence, "
                "evidenceSummary. Each taskRef must include slug, name, group, confidence, and evidence. Each methodRef "
                "must include slug, name, area, confidence, and evidence. Extract benchmark entries only when the paper "
                "explicitly reports a dataset/benchmark and metric; do not invent missing benchmarks. Each benchmark "
                "must include category, name, metric, value when present, taskSlug when known, confidence, and evidence."
            ),
            LLMMessage.user(json.dumps(context, ensure_ascii=False, sort_keys=True)),
        ],
        temperature=0.1,
        max_tokens=2400,
        response_format={"type": "json_object"},
        metadata={"paper_id": _candidate_paper_id(candidate), "schema": "paper_ingest_classification_v1"},
    )


def _paper_payload_from_ingest(
    candidate: RawSourceItem,
    *,
    paper_id: str,
    pdf_url: str,
    repo_url: str,
    github: GithubRepositoryMetadata,
    thumbnail_url: str | None,
    citation: PaperCitationMetadata | None,
    taxonomy: Mapping[str, Any],
    classification: Mapping[str, Any],
    run_id: str,
    collected_at: str,
) -> Mapping[str, Any]:
    arxiv_id = _candidate_arxiv_id(candidate)
    citation_doi = citation.doi if citation else _citation_doi_for_candidate(candidate)
    published_at = _dt(candidate.published_at) or collected_at
    payload = {
        "id": paper_id,
        "slug": _slugify(candidate.title)[:90] or paper_id,
        "title": candidate.title,
        "abstractSnippet": candidate.summary or candidate.title,
        "authors": list(candidate.authors),
        "publishedAt": published_at,
        "venue": "arXiv",
        "citationCount": citation.citation_count if citation else 0,
        "citationDoi": citation_doi,
        "openAlexId": citation.openalex_id if citation else None,
        "citationFetchedAt": collected_at if citation else None,
        "citationSource": "openalex" if citation else None,
        "tags": list(candidate.tags),
        "taskRefs": taxonomy.get("taskRefs") or [],
        "methodRefs": taxonomy.get("methodRefs") or [],
        "benchmarks": taxonomy.get("benchmarks") or [],
        "paperUrl": candidate.url,
        "arxivId": arxiv_id,
        "arxivUrl": candidate.url,
        "pdfUrl": _normalize_pdf_url(pdf_url),
        "repoUrl": repo_url,
        "githubStars": github.stargazers_count,
        "thumbnailUrl": thumbnail_url,
        "isPublished": True,
        "implementations": [
            {
                "id": f"github-{_slugify(github.full_name)}",
                "name": github.full_name,
                "repoUrl": github.html_url,
                "provider": "github",
                "githubStars": github.stargazers_count,
            }
        ],
        "classification": _classification_record(taxonomy=taxonomy, classification=classification),
        "citation": citation.to_cache_payload(fetched_at=collected_at).get("citation") if citation else None,
        "ingest": {
            "runId": run_id,
            "source": "papers.ingest_github_arxiv_daily",
            "collectedAt": collected_at,
            "githubStarsThresholdPassed": True,
        },
    }
    return {key: value for key, value in payload.items() if value not in (None, "", [], {})}


def _classification_record(*, taxonomy: Mapping[str, Any], classification: Mapping[str, Any]) -> Mapping[str, Any]:
    return sanitize_public_payload(
        {
            "schemaVersion": "paper_ingest_classification_v2",
            "primaryTaskGroup": taxonomy.get("primaryTaskGroup"),
            "secondaryTaskGroups": taxonomy.get("secondaryTaskGroups") or [],
            "confidence": taxonomy.get("confidence") or _float(classification.get("confidence")),
            "evidenceSummary": taxonomy.get("evidenceSummary")
            or _optional_text(classification.get("evidenceSummary") or classification.get("evidence_summary")),
            "modelTaskRefs": classification.get("taskRefs") or classification.get("tasks") or [],
            "modelMethodRefs": classification.get("methodRefs") or classification.get("methods") or [],
            "modelBenchmarks": classification.get("benchmarks") or [],
            "lowConfidenceItems": taxonomy.get("lowConfidenceItems") or [],
            "analysisSource": classification.get("analysisSource"),
            "legacyFallback": classification.get("legacyFallback"),
            "warnings": classification.get("warnings") or [],
        }
    )


def _mark_legacy_classifier_fallback(profile: dict[str, Any], *, error: Exception) -> Mapping[str, Any]:
    warnings = list(_sequence(profile.get("warnings")))
    warnings.append(
        {
            "kind": "legacy_classifier_fallback",
            "reason": "agent_analysis_failed",
            "message": str(error),
        }
    )
    profile["analysisSource"] = "legacy_classifier"
    profile["legacyFallback"] = True
    profile["warnings"] = warnings
    return sanitize_public_payload(profile)


def _new_run_state(run_id: str, *, started: datetime, config: PaperIngestConfig) -> dict[str, Any]:
    return {
        "runId": run_id,
        "status": "running",
        "startedAt": _iso(started),
        "finishedAt": None,
        "candidateLimit": config.candidate_limit,
        "minGithubStars": config.min_github_stars,
        "autoTaxonomyConfidence": config.auto_taxonomy_confidence,
        "candidateCount": 0,
        "processedCount": 0,
        "publishedCount": 0,
        "skippedNoGithubCount": 0,
        "skippedLowStarsCount": 0,
        "repairQueuedCount": 0,
        "blockedCount": 0,
        "failureCount": 0,
        "publishedPaperIds": [],
        "errors": [],
    }


def _progress_run_state(
    state: Mapping[str, Any],
    *,
    published_ids: Sequence[str],
    errors: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    progress = dict(state)
    progress["status"] = "running"
    progress["finishedAt"] = None
    progress["publishedPaperIds"] = list(published_ids)
    progress["errors"] = list(errors)
    return progress


def _run_result_from_state(state: Mapping[str, Any]) -> PaperIngestRunResult:
    return PaperIngestRunResult(
        run_id=str(state["runId"]),
        status=str(state["status"]),
        started_at=str(state["startedAt"]),
        finished_at=str(state.get("finishedAt") or ""),
        candidate_limit=int(state.get("candidateLimit") or DEFAULT_CANDIDATE_LIMIT),
        min_github_stars=int(state.get("minGithubStars") or DEFAULT_MIN_GITHUB_STARS),
        auto_taxonomy_confidence=float(state.get("autoTaxonomyConfidence") or DEFAULT_AUTO_TAXONOMY_CONFIDENCE),
        candidate_count=int(state.get("candidateCount") or 0),
        processed_count=int(state.get("processedCount") or 0),
        published_count=int(state.get("publishedCount") or 0),
        skipped_no_github_count=int(state.get("skippedNoGithubCount") or 0),
        skipped_low_stars_count=int(state.get("skippedLowStarsCount") or 0),
        repair_queued_count=int(state.get("repairQueuedCount") or 0),
        blocked_count=int(state.get("blockedCount") or 0),
        failure_count=int(state.get("failureCount") or 0),
        published_paper_ids=tuple(str(item) for item in _sequence(state.get("publishedPaperIds"))),
        errors=tuple(item for item in _sequence(state.get("errors")) if isinstance(item, Mapping)),
    )


def _fetch_pdf_bytes(url: str, max_bytes: int) -> bytes:
    request = Request(url, headers={"User-Agent": "NewsRoom paper ingest", "Accept": "application/pdf"})
    with urlopen(request, timeout=30) as response:  # nosec B310 - URLs are validated and user-configured sources.
        content_type = response.headers.get("content-type", "")
        if "pdf" not in content_type.casefold() and "octet-stream" not in content_type.casefold():
            raise ValueError(f"unsupported PDF content type: {content_type}")
        body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise ValueError(f"PDF exceeds max bytes: {max_bytes}")
    if not body.startswith(b"%PDF"):
        raise ValueError("response is not a PDF document")
    return body


def _default_llm_client_factory(route: str) -> Any:
    return build_openai_compatible_client_from_config(route_id=route)


def _default_paper_analysis_orchestrator(config: PaperIngestConfig) -> PaperAnalysisOrchestrator:
    return PaperAnalysisOrchestrator(
        workspace=AgentSharedWorkspace(
            SQLiteAgentSessionStore(_agent_session_store_path(config)),
            access_policy=paper_session_access_policy(),
        ),
    )


def _agent_session_store_path(config: PaperIngestConfig) -> Path:
    if config.agent_session_store_path:
        return Path(config.agent_session_store_path).expanduser().resolve()
    return _project_root() / ".newsroom" / "paper-agent-sessions.sqlite3"


def _papers_data_path(configured_path: str | Path | None) -> Path:
    if configured_path is not None:
        return Path(configured_path).expanduser().resolve()
    env_path = os.environ.get(PAPERS_DATA_PATH_ENV)
    if env_path:
        return Path(env_path).expanduser().resolve()
    return _project_root() / ".newsroom" / "papers" / "arxiv-papers.json"


def _state_dir(configured_path: str | Path | None) -> Path:
    if configured_path is not None:
        return Path(configured_path).expanduser().resolve()
    env_path = os.environ.get(PAPERS_INGEST_STATE_DIR_ENV)
    if env_path:
        return Path(env_path).expanduser().resolve()
    return _project_root() / ".newsroom" / "papers"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_json(path: Path, *, default: Mapping[str, Any]) -> Mapping[str, Any]:
    return read_json_object(path, default=default, strict=True)


def _read_json_unlocked(path: Path, *, default: Mapping[str, Any]) -> Mapping[str, Any]:
    return read_json_object_unlocked(path, default=default, strict=True)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    sanitized = sanitize_public_payload(dict(payload))
    write_json_object(path, dict(sanitized) if isinstance(sanitized, Mapping) else {})


def _write_json_unlocked(path: Path, payload: Mapping[str, Any]) -> None:
    sanitized = sanitize_public_payload(dict(payload))
    write_json_object_unlocked(path, dict(sanitized) if isinstance(sanitized, Mapping) else {})


def _openalex_fetch_json(request: Request, timeout_seconds: int) -> Mapping[str, Any]:
    with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310 - fixed OpenAlex API URL.
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("OpenAlex response root must be an object")
    return payload


def _http_error_message(exc: HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", errors="replace")
    except Exception:
        body = ""
    return f"HTTP {exc.code}: {body or exc.reason}"


def _dedupe_strings(values: Sequence[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = _optional_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _dedupe_candidates(candidates: Sequence[RawSourceItem]) -> list[RawSourceItem]:
    seen: set[str] = set()
    result: list[RawSourceItem] = []
    for candidate in candidates:
        key = _candidate_arxiv_id(candidate) or candidate.url or candidate.title
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def _candidate_from_cached_paper(record: Mapping[str, Any], *, fetched_at: datetime) -> RawSourceItem | None:
    title = _optional_text(record.get("title"))
    url = (
        _optional_text(record.get("paperUrl"))
        or _optional_text(record.get("arxivUrl"))
        or _optional_text(record.get("url"))
    )
    if not title or not url:
        return None
    paper_id = _optional_text(record.get("id")) or hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    metadata = {
        "arxiv_id": _cached_arxiv_id(record),
        "pdf_url": _optional_text(record.get("pdfUrl")),
        "repo_url": _optional_text(record.get("repoUrl")),
        "github_stars": record.get("githubStars"),
        "cache_source": "papers_cache",
    }
    return RawSourceItem(
        source_item_id=f"cached-{paper_id}",
        source_id="arxiv",
        source_name="arXiv",
        source_type="arxiv",
        title=title,
        url=url,
        fetched_at=fetched_at,
        published_at=_parse_datetime_optional(record.get("publishedAt")),
        summary=_optional_text(record.get("abstractSnippet") or record.get("summary")),
        raw_content=json.dumps(sanitize_public_payload(dict(record)), ensure_ascii=False, sort_keys=True),
        authors=[str(item) for item in _sequence(record.get("authors")) if str(item).strip()],
        tags=[str(item) for item in _sequence(record.get("tags")) if str(item).strip()],
        language=_optional_text(record.get("language")) or "en",
        metadata={key: value for key, value in metadata.items() if value not in (None, "", [])},
    )


def _paper_needs_taxonomy_backfill(record: Mapping[str, Any]) -> bool:
    classification = record.get("classification")
    if not isinstance(classification, Mapping) or classification.get("schemaVersion") != "paper_ingest_classification_v2":
        return True
    task_refs = _sequence(record.get("taskRefs"))
    method_refs = _sequence(record.get("methodRefs"))
    if not task_refs or not method_refs:
        return True
    for ref in task_refs:
        if not isinstance(ref, Mapping) or normalize_ai_task_group(ref.get("group")) is None:
            return True
    for ref in method_refs:
        if not isinstance(ref, Mapping) or normalize_method_collection(ref.get("area")) is None:
            return True
    for benchmark in _sequence(record.get("benchmarks")) or _sequence(record.get("benchmarkResults")):
        if isinstance(benchmark, Mapping) and _optional_text(benchmark.get("metric")):
            if normalize_benchmark_category(
                benchmark.get("category") or benchmark.get("benchmarkCategory") or benchmark.get("benchmark_category")
            ) is None:
                return True
    return False


def _paper_needs_citation_backfill(record: Mapping[str, Any]) -> bool:
    if not _citation_doi_for_record(record):
        return False
    if _optional_text(record.get("openAlexId")):
        return False
    citation = record.get("citation")
    if isinstance(citation, Mapping) and _optional_text(citation.get("openAlexId")):
        return False
    return True


def _citation_doi_for_record(record: Mapping[str, Any]) -> str | None:
    doi = _normalize_doi(record.get("citationDoi") or record.get("doi"))
    if doi:
        return doi
    arxiv_id = _cached_arxiv_id(record)
    return _arxiv_doi(arxiv_id)


def _citation_doi_for_candidate(candidate: RawSourceItem) -> str | None:
    doi = _normalize_doi(candidate.metadata.get("citationDoi") or candidate.metadata.get("citation_doi") or candidate.metadata.get("doi"))
    if doi:
        return doi
    return _arxiv_doi(_candidate_arxiv_id(candidate))


def _arxiv_doi(arxiv_id: str | None) -> str | None:
    if not arxiv_id:
        return None
    clean_id = arxiv_id.removeprefix("arxiv-").removesuffix(".pdf")
    clean_id = re.sub(r"v\d+$", "", clean_id, flags=re.IGNORECASE)
    return _normalize_doi(f"10.48550/arxiv.{clean_id}")


def _normalize_doi(value: Any) -> str | None:
    text = _optional_text(value)
    if not text:
        return None
    normalized = text.casefold()
    normalized = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", normalized).strip()
    normalized = normalized.rstrip(".,;:)]}>'\"")
    return normalized or None


def _openalex_title_matches_candidate(candidate: RawSourceItem, citation: PaperCitationMetadata) -> bool:
    return _titles_match(candidate.title, citation.display_name)


def _openalex_title_matches_paper(record: Mapping[str, Any], citation: PaperCitationMetadata) -> bool:
    return _titles_match(_optional_text(record.get("title")) or "", citation.display_name)


def _titles_match(left: str, right: str | None) -> bool:
    normalized_left = _normalize_title(left)
    normalized_right = _normalize_title(right or "")
    if not normalized_left or not normalized_right:
        return True
    return (
        normalized_left == normalized_right
        or normalized_left in normalized_right
        or normalized_right in normalized_left
    )


def _normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", html.unescape(value).casefold()).strip()


def _cached_paper_sections(
    record: Mapping[str, Any],
    paper_id: str,
    repository: TextExtractionRepository,
) -> tuple[Mapping[str, Any], ...]:
    candidate_ids = []
    for value in (paper_id, _optional_text(record.get("id"))):
        if value and value not in candidate_ids:
            candidate_ids.append(value)
    for candidate_id in candidate_ids:
        sections = repository.read_latest_sections(candidate_id)
        if sections:
            return sections
    return ()


def _join_paper_text(
    record: Mapping[str, Any],
    sections: Sequence[Mapping[str, Any]],
    *,
    fallback_text: str | None = None,
) -> str:
    parts = [
        _optional_text(record.get("title")),
        _optional_text(record.get("abstractSnippet") or record.get("summary")),
    ]
    section_texts = [
        _optional_text(item.get("textExcerpt") or item.get("summary"))
        for item in sections
        if isinstance(item, Mapping)
    ]
    parts.extend(section_texts)
    if not any(section_texts) and fallback_text:
        parts.append(_optional_text(fallback_text))
    return "\n\n".join(part for part in parts if part)


def _cached_arxiv_id(record: Mapping[str, Any]) -> str | None:
    explicit = _optional_text(record.get("arxivId"))
    if explicit:
        return explicit.removeprefix("arxiv-")
    paper_id = _optional_text(record.get("id"))
    if paper_id and paper_id.startswith("arxiv-"):
        return paper_id.removeprefix("arxiv-")
    for key in ("paperUrl", "arxivUrl", "pdfUrl"):
        value = _optional_text(record.get(key))
        if not value:
            continue
        match = _ARXIV_ID_PATTERN.search(value)
        if match:
            return match.group(1).removesuffix(".pdf")
    return None


def _candidate_paper_id(candidate: RawSourceItem) -> str:
    arxiv_id = _candidate_arxiv_id(candidate)
    if arxiv_id:
        return f"arxiv-{arxiv_id.replace('/', '-')}"
    return f"paper-{hashlib.sha256(candidate.url.encode('utf-8')).hexdigest()[:16]}"


def _candidate_arxiv_id(candidate: RawSourceItem) -> str | None:
    metadata_id = _optional_text(candidate.metadata.get("arxiv_id"))
    if metadata_id:
        return metadata_id.removesuffix(".pdf")
    for value in (candidate.url, _optional_text(candidate.metadata.get("pdf_url"))):
        match = _ARXIV_ID_PATTERN.search(value)
        if match:
            return match.group(1).removesuffix(".pdf")
    return None


def _candidate_pdf_url(candidate: RawSourceItem) -> str | None:
    pdf_url = _optional_text(candidate.metadata.get("pdf_url"))
    if pdf_url:
        return _normalize_pdf_url(pdf_url)
    arxiv_id = _candidate_arxiv_id(candidate)
    if arxiv_id:
        return f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    return None


def _candidate_search_text(candidate: RawSourceItem) -> str:
    return "\n".join(
        [
            candidate.title,
            candidate.summary or "",
            candidate.raw_content or "",
            json.dumps(sanitize_public_payload(candidate.metadata), ensure_ascii=False, sort_keys=True),
        ]
    )


def _extract_github_repo_url(value: str) -> str | None:
    match = _GITHUB_REPO_PATTERN.search(value or "")
    if not match:
        return None
    return _normalize_github_repo_url(match.group(0))


def _normalize_github_repo_url(value: str | None) -> str | None:
    text = (value or "").strip().rstrip(".,;:)]}>'\"")
    if not text:
        return None
    try:
        parsed = urlparse(text.replace("http://", "https://", 1))
    except ValueError:
        return None
    if parsed.scheme != "https" or parsed.netloc.casefold().removeprefix("www.") != "github.com":
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    owner = parts[0].strip().rstrip(".,;:)]}>'\"")
    repo = parts[1].strip().removesuffix(".git").rstrip(".,;:)]}>'\"")
    if not owner or not repo:
        return None
    return f"https://github.com/{owner}/{repo}"


def _repository_slug_from_url(repo_url: str) -> str:
    parsed = urlparse(repo_url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise PaperIngestError("GitHub repository URL did not include owner/repo", code="github_url_invalid", step="github_extract")
    return GithubRepository(owner=parts[0], name=parts[1]).slug()


def _normalize_pdf_url(value: str | None) -> str | None:
    text = (value or "").strip().rstrip(".,;:)]}>'\"")
    if not text:
        return None
    try:
        parsed = urlparse(text.replace("http://", "https://", 1))
    except ValueError:
        return None
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    normalized = parsed.geturl()
    if parsed.netloc.endswith("arxiv.org") and "/pdf/" in parsed.path and not normalized.endswith(".pdf"):
        normalized = f"{normalized}.pdf"
    return normalized


def _normalized_https_url(value: Any) -> str | None:
    text = _optional_text(value)
    if not text:
        return None
    try:
        parsed = urlparse(text.replace("http://", "https://", 1))
    except ValueError:
        return None
    return parsed.geturl() if parsed.scheme == "https" and parsed.netloc else None


def _thumbnail_url(path: Path | None) -> str | None:
    if path is None:
        return None
    return f"/api/papers/assets/thumbnails/{path.name}"


def _source_hash(candidate: RawSourceItem, *, pdf_url: str | None, repo_url: str | None) -> str:
    payload = {
        "id": _candidate_paper_id(candidate),
        "url": candidate.url,
        "pdfUrl": pdf_url,
        "repoUrl": repo_url,
        "updatedAt": _dt(candidate.published_at),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _parse_json_object(content: str) -> tuple[Mapping[str, Any], bool]:
    stripped = content.strip()
    if not stripped:
        return {}, False
    try:
        payload = json.loads(stripped)
        return (payload if isinstance(payload, Mapping) else {}), False
    except json.JSONDecodeError:
        pass
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        try:
            payload = json.loads(stripped[start : end + 1])
            return (payload if isinstance(payload, Mapping) else {}), True
        except json.JSONDecodeError:
            return {}, False
    return {}, False


def _public_ref(ref: Mapping[str, Any], *, confidence: float, evidence: str | None) -> Mapping[str, Any]:
    payload = {
        "id": _optional_text(ref.get("id")) or f"ref-{_slugify(_optional_text(ref.get('slug')) or _optional_text(ref.get('name')))}",
        "slug": _optional_text(ref.get("slug")),
        "name": _optional_text(ref.get("name")),
        "nameZh": _optional_text(ref.get("nameZh")),
        "group": _optional_text(ref.get("group")),
        "area": _optional_text(ref.get("area")),
        "confidence": confidence,
        "evidence": evidence,
    }
    return {key: value for key, value in payload.items() if value not in (None, "", [], {})}


def _dedupe_refs(refs: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    seen: set[str] = set()
    result: list[Mapping[str, Any]] = []
    for ref in refs:
        slug = _optional_text(ref.get("slug"))
        if not slug or slug in seen:
            continue
        seen.add(slug)
        result.append(ref)
    return result


def _first_valid_task_group(value: Any) -> str | None:
    for item in _sequence(value):
        if not isinstance(item, Mapping):
            continue
        group = normalize_ai_task_group(item.get("group") or item.get("taskGroup"))
        if group:
            return group
    return None


def _normalize_secondary_task_groups(value: Any) -> tuple[list[str], list[str]]:
    groups: list[str] = []
    invalid: list[str] = []
    for item in _sequence(value):
        normalized = normalize_ai_task_group(item)
        if normalized:
            if normalized not in groups:
                groups.append(normalized)
            continue
        text = _optional_text(item)
        if text:
            invalid.append(text)
    if len(groups) > 2:
        invalid.extend(groups[2:])
        groups = groups[:2]
    return groups, invalid


def _add_ref_to_index(index: dict[str, Mapping[str, Any]], value: Any) -> None:
    if not isinstance(value, Mapping):
        return
    slug = _optional_text(value.get("slug"))
    name = _optional_text(value.get("name"))
    ref_id = _optional_text(value.get("id"))
    if not slug or not name:
        return
    ref = {"id": ref_id or f"ref-{slug}", "slug": slug, "name": name}
    for key in ("nameZh", "group", "area"):
        text = _optional_text(value.get(key))
        if text:
            ref[key] = text
    index.setdefault(slug, ref)


def _deep_merge(existing: Mapping[str, Any], incoming: Mapping[str, Any]) -> Mapping[str, Any]:
    merged = dict(existing)
    for key, value in incoming.items():
        if value not in (None, "", [], {}):
            merged[key] = value
    return merged


def _repair_action_for(error_code: str, step: str) -> str:
    normalized = f"{step}:{error_code}".casefold()
    if "github" in normalized:
        return "normalize_github_url_and_retry_metadata_fetch"
    if "pdf" in normalized:
        return "normalize_pdf_url_refetch_and_extract"
    if "citation" in normalized or "openalex" in normalized:
        return "normalize_doi_refetch_openalex_and_verify_title"
    if "json" in normalized or "classif" in normalized:
        return "inject_prompt_memory_and_reclassify"
    return "retry_with_backoff_and_prompt_memory"


def _is_hard_block_error(code: str, message: str) -> bool:
    text = f"{code} {message}".casefold()
    return any(hint in text for hint in _HARD_BLOCK_HINTS)


def _section_type_from_text(text: str, page_number: int) -> str:
    prefix = text[:1200].casefold()
    if page_number == 1:
        return "abstract"
    if "benchmark" in prefix or "dataset" in prefix:
        return "benchmark"
    if "experiment" in prefix or "evaluation" in prefix:
        return "experiment"
    if "method" in prefix or "approach" in prefix:
        return "method"
    if "conclusion" in prefix:
        return "conclusion"
    return "unknown"


def _truncate_middle(value: str, max_chars: int) -> str:
    text = value.strip()
    if len(text) <= max_chars:
        return text
    head = max_chars // 2
    tail = max_chars - head
    return f"{text[:head]}\n\n[... omitted {len(text) - max_chars} characters ...]\n\n{text[-tail:]}"


def _normalize_space(value: str) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", value).strip()


def _slugify(value: str | None) -> str:
    text = (value or "").strip().casefold()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:80]


def _safe_file_key(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip(".-")
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    if not normalized:
        return digest
    prefix = normalized[: max(1, 140 - len(digest) - 1)].rstrip(".-")
    return f"{prefix}-{digest}" if prefix else digest


def _is_safe_file_name(value: str) -> bool:
    text = str(value or "").strip()
    if not text or text != value or len(text) > 180:
        return False
    if "/" in text or "\\" in text or text in {".", ".."}:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]+", text))


def _stable_id(*parts: str) -> str:
    encoded = "|".join(parts).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def _dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _iso(value: datetime) -> str:
    return _dt(value) or datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parse_datetime_optional(value: Any) -> datetime | None:
    text = _optional_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []


def _float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return max(0.0, min(float(value), 1.0))
    if isinstance(value, str):
        try:
            return max(0.0, min(float(value), 1.0))
        except ValueError:
            return default
    return default


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


def _positive_int_env(name: str, default: int) -> int:
    return _positive_int(os.environ.get(name)) or default


def _float_env(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def _optional_env(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    text = value.strip()
    return text or None
