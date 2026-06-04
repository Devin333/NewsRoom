from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from framework.llm import (
    DEFAULT_MODEL_ROUTE_ID,
    LLMConfigurationError,
    LLMMessage,
    LLMProviderError,
    LLMRequest,
    build_openai_compatible_client_from_config,
)
from business.boards.paper_radar.public_mapper import map_paper_radar_artifact_to_public_papers, sanitize_public_payload
from business.boards.paper_radar.reader_agent import (
    PaperReaderAnswer,
    answer_cache_key,
    answer_from_payload,
    answer_reader_question,
    copy_answer,
)
from business.boards.paper_radar.reader_payload_builder import (
    PaperReaderPayload,
    PaperReaderQuality,
    PaperSection,
    build_reader_payload,
)
from interfaces.services.paper_artifact_repository import PaperArtifactRepository
from interfaces.services.json_file_store import locked_json_file, read_json_object, read_json_object_unlocked, write_json_object, write_json_object_unlocked
from interfaces.services.paper_reader_cache_repository import (
    PaperReaderCacheRepository,
    TextExtractionRepository,
    reader_cache_source_hash,
)
from interfaces.services.paper_taxonomy_categories import (
    normalize_ai_task_group,
    normalize_benchmark_category,
    normalize_method_collection,
)


PaperPeriod = Literal["daily", "weekly", "monthly", "all"]
PaperSort = Literal["trending", "newest", "most_cited"]
PaperLocale = Literal["zh", "en"]

PAPERS_DATA_PATH_ENV = "NEWSROOM_PAPERS_DATA_PATH"
PAPERS_SUMMARY_CACHE_PATH_ENV = "NEWSROOM_PAPERS_AI_SUMMARY_CACHE_PATH"
PAPERS_SUMMARY_EVENTS_PATH_ENV = "NEWSROOM_PAPERS_SUMMARY_EVENTS_PATH"
PAPERS_SUMMARY_MODEL_ROUTE_ENV = "NEWS_PAPERS_SUMMARY_MODEL_ROUTE"
PAPER_SUMMARY_SCHEMA_VERSION = "v2"
DEFAULT_LIMIT = 1000
MAX_LIMIT = 5000
DEFAULT_OPS_STATS_WINDOW_HOURS = 24
MAX_OPS_STATS_WINDOW_HOURS = 24 * 30

logger = logging.getLogger(__name__)

_GITHUB_REPO_PATTERN = re.compile(r"https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


class PaperCacheNotFoundError(FileNotFoundError):
    pass


class PaperCacheInvalidError(RuntimeError):
    pass


class PaperNotFoundError(KeyError):
    pass


class PaperSummaryUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class PaperRef:
    id: str
    slug: str
    name: str
    nameZh: str | None = None
    group: str | None = None
    area: str | None = None
    confidence: float | None = None
    evidence: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {"id": self.id, "slug": self.slug, "name": self.name}
        if self.nameZh:
            payload["nameZh"] = self.nameZh
        if self.group:
            payload["group"] = self.group
        if self.area:
            payload["area"] = self.area
        if self.confidence is not None:
            payload["confidence"] = self.confidence
        if self.evidence:
            payload["evidence"] = self.evidence
        return payload


@dataclass(frozen=True)
class PaperImplementation:
    id: str
    name: str
    repoUrl: str
    provider: str = "github"
    githubStars: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "repoUrl": self.repoUrl,
            "provider": self.provider,
        }
        if self.githubStars is not None:
            payload["githubStars"] = self.githubStars
        return payload


@dataclass(frozen=True)
class PaperBenchmarkResult:
    id: str
    name: str
    category: str | None = None
    metric: str | None = None
    value: str | int | float | None = None
    taskSlug: str | None = None
    url: str | None = None
    confidence: float | None = None
    evidence: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"id": self.id, "name": self.name}
        if self.category is not None:
            payload["category"] = self.category
        if self.metric is not None:
            payload["metric"] = self.metric
        if self.value is not None:
            payload["value"] = self.value
        if self.taskSlug is not None:
            payload["taskSlug"] = self.taskSlug
        if self.url is not None:
            payload["url"] = self.url
        if self.confidence is not None:
            payload["confidence"] = self.confidence
        if self.evidence is not None:
            payload["evidence"] = self.evidence
        return payload


@dataclass(frozen=True)
class PaperAISummary:
    paperId: str
    locale: PaperLocale
    modelRoute: str
    abstractHash: str
    summary: str
    keyInsights: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    contributions: tuple[str, ...] = ()
    methodSummary: str | None = None
    experimentSummary: str | None = None
    engineeringRelevance: str | None = None
    readingDifficulty: Literal["low", "medium", "high"] | None = None
    recommendedAudience: tuple[str, ...] = ()
    summarySchemaVersion: str | None = None
    generatedAt: str = ""
    cached: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "paperId": self.paperId,
            "locale": self.locale,
            "modelRoute": self.modelRoute,
            "abstractHash": self.abstractHash,
            "summary": self.summary,
            "keyInsights": list(self.keyInsights),
            "limitations": list(self.limitations),
            "generatedAt": self.generatedAt,
            "cached": self.cached,
        }
        if self.contributions:
            payload["contributions"] = list(self.contributions)
        for key, value in (
            ("methodSummary", self.methodSummary),
            ("experimentSummary", self.experimentSummary),
            ("engineeringRelevance", self.engineeringRelevance),
            ("readingDifficulty", self.readingDifficulty),
            ("summarySchemaVersion", self.summarySchemaVersion),
        ):
            if value:
                payload[key] = value
        if self.recommendedAudience:
            payload["recommendedAudience"] = list(self.recommendedAudience)
        return sanitize_public_payload(payload)


@dataclass(frozen=True)
class PublicPaper:
    id: str
    slug: str
    title: str
    abstractSnippet: str
    authors: tuple[str, ...]
    publishedAt: str
    venue: str | None
    tags: tuple[str, ...]
    taskRefs: tuple[PaperRef, ...]
    methodRefs: tuple[PaperRef, ...]
    paperUrl: str
    titleZh: str | None = None
    abstractSnippetZh: str | None = None
    citationCount: int | None = None
    citationDoi: str | None = None
    githubMomentum: float | None = None
    githubStars: int | None = None
    thumbnailUrl: str | None = None
    arxivId: str | None = None
    arxivUrl: str | None = None
    pdfUrl: str | None = None
    repoUrl: str | None = None
    projectUrl: str | None = None
    isPublished: bool = True
    implementations: tuple[PaperImplementation, ...] = ()
    benchmarks: tuple[PaperBenchmarkResult, ...] = ()
    newsroomHeatScore: float | None = None
    aiSummary: PaperAISummary | None = None
    evidenceRefs: tuple[Mapping[str, Any], ...] = ()
    sourceRefs: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "slug": self.slug,
            "title": self.title,
            "abstractSnippet": self.abstractSnippet,
            "authors": list(self.authors),
            "publishedAt": self.publishedAt,
            "tags": list(self.tags),
            "taskRefs": [ref.to_dict() for ref in self.taskRefs],
            "methodRefs": [ref.to_dict() for ref in self.methodRefs],
            "paperUrl": self.paperUrl,
            "isPublished": self.isPublished,
            "implementations": [implementation.to_dict() for implementation in self.implementations],
            "benchmarks": [benchmark.to_dict() for benchmark in self.benchmarks],
        }
        for key, value in (
            ("titleZh", self.titleZh),
            ("abstractSnippetZh", self.abstractSnippetZh),
            ("venue", self.venue),
            ("citationCount", self.citationCount),
            ("citationDoi", self.citationDoi),
            ("githubMomentum", self.githubMomentum),
            ("githubStars", self.githubStars),
            ("thumbnailUrl", self.thumbnailUrl),
            ("arxivId", self.arxivId),
            ("arxivUrl", self.arxivUrl),
            ("pdfUrl", self.pdfUrl),
            ("repoUrl", self.repoUrl),
            ("projectUrl", self.projectUrl),
            ("newsroomHeatScore", self.newsroomHeatScore),
        ):
            if value is not None:
                payload[key] = value
        if self.aiSummary is not None:
            payload["aiSummary"] = self.aiSummary.to_dict()
        if self.evidenceRefs:
            payload["evidenceRefs"] = [sanitize_public_payload(ref) for ref in self.evidenceRefs]
        if self.sourceRefs:
            payload["sourceRefs"] = [sanitize_public_payload(ref) for ref in self.sourceRefs]
        return payload


@dataclass(frozen=True)
class PaperListQuery:
    q: str = ""
    period: PaperPeriod = "all"
    sort: PaperSort = "trending"
    task: str | None = None
    method: str | None = None
    limit: int = DEFAULT_LIMIT
    offset: int = 0


@dataclass(frozen=True)
class PaperListResult:
    papers: tuple[PublicPaper, ...]
    total_count: int
    source_count: int
    limit: int
    offset: int
    source: str
    query: str
    period: PaperPeriod
    sort: PaperSort
    collectedAt: str | None = None
    task: str | None = None
    method: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "query": self.query,
            "period": self.period,
            "sort": self.sort,
            "task": self.task,
            "method": self.method,
            "collectedAt": self.collectedAt,
            "paper_count": len(self.papers),
            "total_count": self.total_count,
            "source_count": self.source_count,
            "limit": self.limit,
            "offset": self.offset,
            "has_next": self.offset + len(self.papers) < self.total_count,
            "papers": [paper.to_dict() for paper in self.papers],
        }


class PapersApplicationService:
    def __init__(
        self,
        *,
        papers_data_path: str | Path | None = None,
        summary_cache_path: str | Path | None = None,
        summary_events_path: str | Path | None = None,
        reader_cache_dir: str | Path | None = None,
        text_extraction_dir: str | Path | None = None,
        reader_cache_repository: PaperReaderCacheRepository | None = None,
        text_extraction_repository: TextExtractionRepository | None = None,
        artifact_repository: PaperArtifactRepository | None = None,
        llm_client_factory: Callable[[str], Any] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._explicit_papers_data_path = papers_data_path is not None or bool(os.environ.get(PAPERS_DATA_PATH_ENV))
        self.papers_data_path = _papers_data_path(papers_data_path)
        self.summary_cache_path = _summary_cache_path(summary_cache_path)
        self.summary_events_path = _summary_events_path(summary_events_path)
        self.reader_cache_repository = reader_cache_repository or PaperReaderCacheRepository(reader_cache_dir)
        self.text_extraction_repository = text_extraction_repository or TextExtractionRepository(text_extraction_dir)
        self.artifact_repository = artifact_repository or PaperArtifactRepository()
        self.llm_client_factory = llm_client_factory or _default_llm_client_factory
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._reader_answer_cache: dict[str, dict[str, Any]] = {}

    def list_papers(self, query: PaperListQuery) -> PaperListResult:
        cache = self._load_cache()
        source = _text(cache.get("source")) or "papers-cache"
        collected_at = _optional_text(cache.get("collectedAt"))
        source_papers = self._published_papers(cache)
        filtered = self._filter_papers(source_papers, query)
        sorted_papers = _sort_papers(filtered, query.sort)
        page = sorted_papers[query.offset : query.offset + query.limit]
        return PaperListResult(
            papers=tuple(page),
            total_count=len(sorted_papers),
            source_count=len(source_papers),
            limit=query.limit,
            offset=query.offset,
            source=source,
            query=query.q,
            period=query.period,
            sort=query.sort,
            task=query.task,
            method=query.method,
            collectedAt=collected_at,
        )

    def get_paper(self, paper_id: str) -> PublicPaper:
        normalized_id = paper_id.strip()
        if not normalized_id:
            raise PaperNotFoundError("paper not found")
        for paper in self._published_papers(self._load_cache()):
            if paper.id == normalized_id or paper.slug == normalized_id:
                cached_summary = self._cached_summary_for(paper, self._summary_route(), locale="en")
                return _with_summary(paper, cached_summary)
        raise PaperNotFoundError(f"paper not found: {paper_id}")

    def list_published_papers(self, *, limit: int | None = None, offset: int = 0) -> tuple[PublicPaper, ...]:
        if limit is not None and limit <= 0:
            raise ValueError("limit must be greater than zero")
        if offset < 0:
            raise ValueError("offset must be non-negative")
        papers = self._published_papers(self._load_cache())
        if limit is None:
            return tuple(papers[offset:])
        return tuple(papers[offset : offset + limit])

    def get_or_generate_summary(self, paper_id: str, *, locale: PaperLocale, refresh: bool = False) -> PaperAISummary:
        paper = self.get_paper(paper_id)
        route = self._summary_route()
        started = time.perf_counter()
        try:
            if not refresh:
                cached = self._cached_summary_for(paper, route, locale=locale)
                if cached is not None:
                    self._record_summary_event(
                        paper_id=paper.id,
                        locale=locale,
                        model_route=route,
                        outcome="cache_hit",
                        duration_ms=_duration_ms(started),
                        cache_hit=True,
                    )
                    return _copy_summary(cached, cached=True)

            summary = self._generate_summary(paper, locale=locale, route=route)
            self._upsert_summary_cache(summary_cache_key(paper, locale=locale, route=route), summary.to_dict() | {"cached": False})
            self._record_summary_event(
                paper_id=paper.id,
                locale=locale,
                model_route=route,
                outcome="generated",
                duration_ms=_duration_ms(started),
                cache_hit=False,
            )
            return summary
        except PaperSummaryUnavailableError as exc:
            summary = _fallback_summary(paper, locale=locale, route=route, generated_at=self.clock())
            self._upsert_summary_cache(summary_cache_key(paper, locale=locale, route=route), summary.to_dict() | {"cached": False})
            self._record_summary_event(
                paper_id=paper.id,
                locale=locale,
                model_route=route,
                outcome="fallback_generated",
                duration_ms=_duration_ms(started),
                cache_hit=False,
                error_code=f"paper_summary_fallback:{type(exc).__name__}",
            )
            return summary

    def get_reader_payload(self, paper_id: str, *, locale: PaperLocale) -> PaperReaderPayload:
        paper = self.get_paper(paper_id)
        summary = self._cached_summary_for(paper, self._summary_route(), locale=locale)
        if summary is None and paper.aiSummary is not None and paper.aiSummary.locale == locale:
            summary = paper.aiSummary
        candidates = tuple(self._published_papers(self._load_cache()))
        base_source_hash = reader_source_hash(paper, ai_summary=summary, related_paper_candidates=candidates)
        extracted_sections = self.text_extraction_repository.read_sections(paper.id, base_source_hash)
        if not extracted_sections:
            extracted_sections = self.text_extraction_repository.read_latest_sections(paper.id)
        source_hash = reader_cache_source_hash(base_source_hash, extracted_sections)
        cached_reader = _reader_payload_from_cache(self.reader_cache_repository.read(paper.id, source_hash))
        if cached_reader is not None:
            return cached_reader
        reader = build_reader_payload(
            paper,
            ai_summary=summary,
            related_paper_candidates=candidates,
            extracted_section_payloads=extracted_sections,
        )
        cached_at = self.clock().isoformat().replace("+00:00", "Z")
        if not self.reader_cache_repository.write(
            paper.id,
            source_hash,
            reader.to_dict(),
            cached_at=cached_at,
            base_source_hash=base_source_hash,
        ):
            logger.warning("paper reader cache write failed", extra={"paper_id": paper.id})
        return reader

    def get_paper_sections(self, paper_id: str, *, locale: PaperLocale) -> tuple[Mapping[str, Any], ...]:
        reader = self.get_reader_payload(paper_id, locale=locale)
        return tuple(section.to_dict() for section in reader.sections)

    def get_related_papers(self, paper_id: str) -> tuple[Mapping[str, Any], ...]:
        reader = self.get_reader_payload(paper_id, locale="en")
        return tuple(reader.relatedPapers)

    def get_paper_graph(self, paper_id: str) -> Mapping[str, Any]:
        reader = self.get_reader_payload(paper_id, locale="en")
        return _paper_graph_payload(reader)

    def list_tasks(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(_task_index(self._published_papers(self._load_cache())))

    def list_methods(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(_method_index(self._published_papers(self._load_cache())))

    def ask_paper(self, paper_id: str, *, question: str, locale: PaperLocale) -> PaperReaderAnswer:
        normalized_question = " ".join(question.strip().split())
        if not normalized_question:
            raise ValueError("question is required")
        reader = self.get_reader_payload(paper_id, locale=locale)
        cache_key = answer_cache_key(reader, question=normalized_question, locale=locale)
        cached = answer_from_payload(self._reader_answer_cache.get(cache_key, {}))
        if cached is not None:
            return copy_answer(cached, cached=True)
        answer = answer_reader_question(
            reader,
            question=normalized_question,
            locale=locale,
            generated_at=self.clock(),
        )
        self._reader_answer_cache[cache_key] = answer.to_dict() | {"cached": False}
        return answer

    def get_ops_stats(self, *, window_hours: int = DEFAULT_OPS_STATS_WINDOW_HOURS) -> Mapping[str, Any]:
        normalized_window_hours = _normalized_window_hours(window_hours)
        now = self.clock()
        window_start = now - timedelta(hours=normalized_window_hours)
        paper_cache = _paper_cache_stats(self)
        summary_cache = _summary_cache_stats(self.summary_cache_path)
        summary_events = _summary_event_stats(self.summary_events_path, window_start=window_start, window_end=now)
        reader_cache = _directory_artifact_stats(self.reader_cache_repository.cache_dir)
        text_extraction = _directory_artifact_stats(self.text_extraction_repository.extraction_dir)
        state_inputs = (
            paper_cache,
            summary_cache,
            summary_events,
            reader_cache,
            text_extraction,
        )
        data_state = _ops_data_state(state_inputs)
        payload = {
            "dataState": data_state,
            "windowHours": normalized_window_hours,
            "windowStart": now_to_iso(window_start),
            "windowEnd": now_to_iso(now),
            "paperCache": paper_cache,
            "summaryCache": summary_cache,
            "summaryEvents": summary_events,
            "readerCache": reader_cache,
            "textExtraction": text_extraction,
            "lastUpdatedAt": _latest_timestamp(
                [
                    paper_cache.get("lastUpdatedAt"),
                    summary_cache.get("lastUpdatedAt"),
                    summary_events.get("lastUpdatedAt"),
                    reader_cache.get("lastUpdatedAt"),
                    text_extraction.get("lastUpdatedAt"),
                ]
            ),
        }
        return sanitize_public_payload(payload)

    def _record_summary_event(
        self,
        *,
        paper_id: str,
        locale: PaperLocale,
        model_route: str,
        outcome: Literal["cache_hit", "generated", "failed", "fallback_generated"],
        duration_ms: int,
        cache_hit: bool,
        error_code: str | None = None,
    ) -> None:
        payload = {
            "timestamp": self.clock().isoformat().replace("+00:00", "Z"),
            "paperId": paper_id,
            "locale": locale,
            "modelRoute": model_route,
            "outcome": outcome,
            "durationMs": max(0, duration_ms),
            "cacheHit": bool(cache_hit),
            "schemaVersion": PAPER_SUMMARY_SCHEMA_VERSION,
        }
        if error_code:
            payload["errorCode"] = error_code
        try:
            self.summary_events_path.parent.mkdir(parents=True, exist_ok=True)
            with self.summary_events_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(sanitize_public_payload(payload), ensure_ascii=False, sort_keys=True))
                handle.write("\n")
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("paper summary event write failed", extra={"paper_id": paper_id, "reason": str(exc)})

    def _published_papers(self, cache: Mapping[str, Any]) -> list[PublicPaper]:
        raw_papers = cache.get("papers")
        papers = [_paper_payload(raw_paper) for raw_paper in _sequence(raw_papers)]
        return [paper for paper in papers if paper is not None and paper.isPublished]

    def _filter_papers(self, papers: list[PublicPaper], query: PaperListQuery) -> list[PublicPaper]:
        filtered = [paper for paper in papers if _matches_period(paper, query.period, now=self.clock())]
        normalized_query = query.q.strip().casefold()
        if normalized_query:
            filtered = [paper for paper in filtered if normalized_query in _paper_search_text(paper)]
        if query.task:
            task = query.task.strip().casefold()
            filtered = [
                paper
                for paper in filtered
                if any(ref.slug.casefold() == task or ref.name.casefold() == task for ref in paper.taskRefs)
            ]
        if query.method:
            method = query.method.strip().casefold()
            filtered = [
                paper
                for paper in filtered
                if any(ref.slug.casefold() == method or ref.name.casefold() == method for ref in paper.methodRefs)
            ]
        return filtered

    def _load_cache(self) -> Mapping[str, Any]:
        if not self._explicit_papers_data_path:
            artifact_payload = self.artifact_repository.latest_paper_radar_payload()
            if artifact_payload is not None:
                mapped = map_paper_radar_artifact_to_public_papers(artifact_payload)
                if mapped.get("papers"):
                    return mapped
        if not self.papers_data_path.exists():
            raise PaperCacheNotFoundError(str(self.papers_data_path))
        try:
            cache = json.loads(self.papers_data_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PaperCacheInvalidError(str(exc)) from exc
        if not isinstance(cache, Mapping):
            raise PaperCacheInvalidError("papers cache root must be an object")
        return cache

    def _summary_route(self) -> str:
        return os.environ.get(PAPERS_SUMMARY_MODEL_ROUTE_ENV) or DEFAULT_MODEL_ROUTE_ID

    def _cached_summary_for(
        self,
        paper: PublicPaper,
        route: str,
        *,
        locale: PaperLocale,
    ) -> PaperAISummary | None:
        raw = self._read_summary_cache().get(summary_cache_key(paper, locale=locale, route=route))
        if not isinstance(raw, Mapping):
            return None
        summary = _summary_from_payload(raw)
        return summary

    def _generate_summary(self, paper: PublicPaper, *, locale: PaperLocale, route: str) -> PaperAISummary:
        try:
            client = self.llm_client_factory(route)
            response = client.complete(_summary_request(paper, locale=locale))
        except (LLMConfigurationError, LLMProviderError, RuntimeError, OSError, ValueError) as exc:
            raise PaperSummaryUnavailableError(str(exc)) from exc

        payload = _parse_summary_response(_text(getattr(response, "content", "")))
        summary = _text(payload.get("summary"))
        if not summary:
            raise PaperSummaryUnavailableError("LLM summary response did not include summary text")
        return PaperAISummary(
            paperId=paper.id,
            locale=locale,
            modelRoute=route,
            abstractHash=paper_abstract_hash(paper),
            summary=summary,
            keyInsights=tuple(_string_list(payload.get("keyInsights") or payload.get("key_insights"))),
            limitations=tuple(_string_list(payload.get("limitations"))),
            contributions=tuple(_string_list(payload.get("contributions"))),
            methodSummary=_optional_text(payload.get("methodSummary") or payload.get("method_summary")),
            experimentSummary=_optional_text(payload.get("experimentSummary") or payload.get("experiment_summary")),
            engineeringRelevance=_optional_text(payload.get("engineeringRelevance") or payload.get("engineering_relevance")),
            readingDifficulty=_reading_difficulty(payload.get("readingDifficulty") or payload.get("reading_difficulty")),
            recommendedAudience=tuple(_string_list(payload.get("recommendedAudience") or payload.get("recommended_audience"))),
            summarySchemaVersion=PAPER_SUMMARY_SCHEMA_VERSION,
            generatedAt=self.clock().isoformat().replace("+00:00", "Z"),
            cached=False,
        )

    def _read_summary_cache(self) -> dict[str, Any]:
        return read_json_object(self.summary_cache_path, default={})

    def _write_summary_cache(self, payload: Mapping[str, Any]) -> None:
        write_json_object(self.summary_cache_path, dict(payload))

    def _upsert_summary_cache(self, key: str, value: Mapping[str, Any]) -> None:
        with locked_json_file(self.summary_cache_path) as path:
            payload = read_json_object_unlocked(path, default={})
            payload[key] = dict(value)
            write_json_object_unlocked(path, payload)


def _duration_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def _normalized_window_hours(value: int) -> int:
    if not isinstance(value, int) or value < 1:
        return DEFAULT_OPS_STATS_WINDOW_HOURS
    return min(value, MAX_OPS_STATS_WINDOW_HOURS)


def now_to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _paper_cache_stats(service: PapersApplicationService) -> Mapping[str, Any]:
    file_exists = service.papers_data_path.exists()
    try:
        cache = service._load_cache()
    except PaperCacheNotFoundError:
        return {
            "status": "missing",
            "exists": False,
            "paperCount": 0,
            "collectedAt": None,
            "source": None,
            "lastUpdatedAt": None,
        }
    except PaperCacheInvalidError:
        return {
            "status": "invalid",
            "exists": file_exists,
            "paperCount": 0,
            "collectedAt": None,
            "source": None,
            "lastUpdatedAt": _path_mtime_iso(service.papers_data_path),
        }
    papers = service._published_papers(cache)
    return {
        "status": "ready",
        "exists": file_exists,
        "paperCount": len(papers),
        "collectedAt": _optional_text(cache.get("collectedAt")),
        "source": _optional_text(cache.get("source")) or "papers-cache",
        "lastUpdatedAt": _path_mtime_iso(service.papers_data_path) or _optional_text(cache.get("collectedAt")),
    }


def _summary_cache_stats(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        return {
            "status": "missing",
            "exists": False,
            "entryCount": 0,
            "v2EntryCount": 0,
            "localeCounts": {},
            "modelRouteCounts": {},
            "lastGeneratedAt": None,
            "lastUpdatedAt": None,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "status": "invalid",
            "exists": True,
            "entryCount": 0,
            "v2EntryCount": 0,
            "localeCounts": {},
            "modelRouteCounts": {},
            "lastGeneratedAt": None,
            "lastUpdatedAt": _path_mtime_iso(path),
        }
    if not isinstance(payload, Mapping):
        return {
            "status": "invalid",
            "exists": True,
            "entryCount": 0,
            "v2EntryCount": 0,
            "localeCounts": {},
            "modelRouteCounts": {},
            "lastGeneratedAt": None,
            "lastUpdatedAt": _path_mtime_iso(path),
        }

    locale_counts: dict[str, int] = {}
    model_route_counts: dict[str, int] = {}
    last_generated_at: str | None = None
    v2_count = 0
    for key, value in payload.items():
        if not isinstance(value, Mapping):
            continue
        sanitized = sanitize_public_payload(value)
        if not isinstance(sanitized, Mapping):
            continue
        schema_version = _optional_text(
            sanitized.get("summarySchemaVersion") or sanitized.get("summary_schema_version")
        )
        if schema_version == PAPER_SUMMARY_SCHEMA_VERSION or str(key).endswith(f":{PAPER_SUMMARY_SCHEMA_VERSION}"):
            v2_count += 1
        locale = _optional_text(sanitized.get("locale"))
        if locale:
            _increment_count(locale_counts, locale)
        route = _optional_text(sanitized.get("modelRoute") or sanitized.get("model_route"))
        if route:
            _increment_count(model_route_counts, route)
        generated_at = _optional_text(sanitized.get("generatedAt") or sanitized.get("generated_at"))
        last_generated_at = _latest_timestamp([last_generated_at, generated_at])

    return {
        "status": "ready",
        "exists": True,
        "entryCount": len(payload),
        "v2EntryCount": v2_count,
        "localeCounts": locale_counts,
        "modelRouteCounts": model_route_counts,
        "lastGeneratedAt": last_generated_at,
        "lastUpdatedAt": _path_mtime_iso(path) or last_generated_at,
    }


def _summary_event_stats(path: Path, *, window_start: datetime, window_end: datetime) -> Mapping[str, Any]:
    if not path.exists():
        return _empty_summary_event_stats(status="missing", exists=False)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return _empty_summary_event_stats(status="invalid", exists=True, last_updated_at=_path_mtime_iso(path))

    partial = False
    events: list[Mapping[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            partial = True
            continue
        event = _safe_summary_event(raw)
        event_time = _datetime(_text(event.get("timestamp")))
        if event_time is None:
            partial = True
            continue
        if window_start <= event_time <= window_end:
            events.append(event)

    outcome_counts: dict[str, int] = {}
    error_code_counts: dict[str, int] = {}
    locale_counts: dict[str, int] = {}
    model_route_counts: dict[str, int] = {}
    recent_failures: list[Mapping[str, Any]] = []
    cache_hit_count = 0
    generated_count = 0
    fallback_generated_count = 0
    failure_count = 0
    durations: list[int] = []
    for event in events:
        outcome = _text(event.get("outcome")) or "unknown"
        _increment_count(outcome_counts, outcome)
        if outcome == "cache_hit":
            cache_hit_count += 1
        elif outcome == "generated":
            generated_count += 1
        elif outcome == "fallback_generated":
            fallback_generated_count += 1
        elif outcome == "failed":
            failure_count += 1
            recent_failures.append(
                {
                    "timestamp": event.get("timestamp"),
                    "paperId": event.get("paperId"),
                    "locale": event.get("locale"),
                    "modelRoute": event.get("modelRoute"),
                    "errorCode": event.get("errorCode") or "paper_summary_unavailable",
                    "durationMs": event.get("durationMs"),
                    "schemaVersion": event.get("schemaVersion"),
                }
            )
        error_code = _optional_text(event.get("errorCode"))
        if error_code:
            _increment_count(error_code_counts, error_code)
        locale = _optional_text(event.get("locale"))
        if locale:
            _increment_count(locale_counts, locale)
        route = _optional_text(event.get("modelRoute"))
        if route:
            _increment_count(model_route_counts, route)
        duration = _int_number(event.get("durationMs"))
        if duration is not None and duration >= 0:
            durations.append(duration)

    recent_failures = sorted(
        recent_failures,
        key=lambda event: _timestamp(_text(event.get("timestamp"))),
        reverse=True,
    )[:5]
    summary_requests = cache_hit_count + generated_count + fallback_generated_count
    hit_rate = round(cache_hit_count / summary_requests, 4) if summary_requests else 0.0
    return {
        "status": "partial" if partial else "ready",
        "exists": True,
        "eventCount": len(events),
        "cacheHitCount": cache_hit_count,
        "generatedCount": generated_count,
        "fallbackGeneratedCount": fallback_generated_count,
        "failureCount": failure_count,
        "hitRate": hit_rate,
        "outcomeCounts": outcome_counts,
        "errorCodeCounts": error_code_counts,
        "localeCounts": locale_counts,
        "modelRouteCounts": model_route_counts,
        "recentFailures": recent_failures,
        "averageDurationMs": round(sum(durations) / len(durations)) if durations else 0,
        "lastUpdatedAt": _latest_timestamp([event.get("timestamp") for event in events]) or _path_mtime_iso(path),
    }


def _empty_summary_event_stats(
    *,
    status: str,
    exists: bool,
    last_updated_at: str | None = None,
) -> Mapping[str, Any]:
    return {
        "status": status,
        "exists": exists,
        "eventCount": 0,
        "cacheHitCount": 0,
        "generatedCount": 0,
        "fallbackGeneratedCount": 0,
        "failureCount": 0,
        "hitRate": 0.0,
        "outcomeCounts": {},
        "errorCodeCounts": {},
        "localeCounts": {},
        "modelRouteCounts": {},
        "recentFailures": [],
        "averageDurationMs": 0,
        "lastUpdatedAt": last_updated_at,
    }


def _safe_summary_event(value: Any) -> Mapping[str, Any]:
    sanitized = sanitize_public_payload(value)
    if not isinstance(sanitized, Mapping):
        return {}
    payload: dict[str, Any] = {}
    for key in (
        "timestamp",
        "paperId",
        "locale",
        "modelRoute",
        "outcome",
        "durationMs",
        "errorCode",
        "cacheHit",
        "schemaVersion",
    ):
        if key in sanitized and sanitized[key] not in (None, "", [], {}):
            payload[key] = sanitized[key]
    return payload


def _directory_artifact_stats(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        return {"status": "missing", "exists": False, "fileCount": 0, "lastUpdatedAt": None}
    if not path.is_dir():
        return {"status": "invalid", "exists": True, "fileCount": 0, "lastUpdatedAt": _path_mtime_iso(path)}
    try:
        files = [file for file in path.glob("*.json") if file.is_file()]
    except OSError:
        return {"status": "invalid", "exists": True, "fileCount": 0, "lastUpdatedAt": _path_mtime_iso(path)}
    return {
        "status": "ready",
        "exists": True,
        "fileCount": len(files),
        "lastUpdatedAt": _latest_timestamp([_path_mtime_iso(file) for file in files]) or _path_mtime_iso(path),
    }


def _ops_data_state(items: Sequence[Mapping[str, Any]]) -> Literal["empty", "partial", "ready"]:
    statuses = {_text(item.get("status")) for item in items}
    if "invalid" in statuses or "partial" in statuses:
        return "partial"
    has_data = any(
        bool(
            _int_number(item.get("paperCount"))
            or _int_number(item.get("entryCount"))
            or _int_number(item.get("eventCount"))
            or _int_number(item.get("fileCount"))
        )
        for item in items
    )
    return "ready" if has_data else "empty"


def _increment_count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _path_mtime_iso(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except OSError:
        return None


def _latest_timestamp(values: Sequence[Any]) -> str | None:
    latest: datetime | None = None
    for value in values:
        parsed = _datetime(_text(value))
        if parsed is not None and (latest is None or parsed > latest):
            latest = parsed
    return latest.isoformat().replace("+00:00", "Z") if latest is not None else None


def _default_llm_client_factory(route: str) -> Any:
    return build_openai_compatible_client_from_config(route_id=route)


def summary_cache_key(paper: PublicPaper, *, locale: PaperLocale, route: str) -> str:
    return ":".join((paper.id, paper_abstract_hash(paper), locale, route, PAPER_SUMMARY_SCHEMA_VERSION))


def legacy_summary_cache_key(paper: PublicPaper, *, locale: PaperLocale, route: str) -> str:
    return ":".join((paper.id, paper_abstract_hash(paper), locale, route))


def paper_abstract_hash(paper: PublicPaper) -> str:
    return hashlib.sha256(paper.abstractSnippet.encode("utf-8")).hexdigest()[:16]


def reader_source_hash(
    paper: PublicPaper,
    *,
    ai_summary: PaperAISummary | None,
    related_paper_candidates: Sequence[PublicPaper],
) -> str:
    paper_payload = paper.to_dict()
    paper_payload.pop("aiSummary", None)
    payload = {
        "paper": paper_payload,
        "aiSummary": ai_summary.to_dict() if ai_summary is not None else None,
        "relatedCandidateIds": [candidate.id for candidate in related_paper_candidates if candidate.isPublished],
    }
    encoded = json.dumps(
        sanitize_public_payload(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _reader_payload_from_cache(payload: Mapping[str, Any] | None) -> PaperReaderPayload | None:
    if not isinstance(payload, Mapping):
        return None
    sanitized = sanitize_public_payload(payload)
    if not isinstance(sanitized, Mapping):
        return None
    paper = _paper_payload(sanitized.get("paper"))
    if paper is None:
        return None
    ai_summary = _summary_from_payload(sanitized.get("aiSummary")) if isinstance(sanitized.get("aiSummary"), Mapping) else None
    sections = tuple(
        section
        for section in (_section_from_payload(item) for item in _sequence(sanitized.get("sections")))
        if section is not None and section.paperId == paper.id
    )
    quality = _quality_from_payload(sanitized.get("quality"), paper_id=paper.id)
    if not sections or quality is None:
        return None
    return PaperReaderPayload(
        paper=paper,
        sections=sections,
        aiSummary=ai_summary,
        readerNotes=tuple(_mapping_list(sanitized.get("readerNotes"))),
        relatedPapers=tuple(_mapping_list(sanitized.get("relatedPapers"))),
        relatedProjects=tuple(_mapping_list(sanitized.get("relatedProjects"))),
        relatedNews=tuple(_mapping_list(sanitized.get("relatedNews"))),
        quality=quality,
    )


def _section_from_payload(payload: Any) -> PaperSection | None:
    if not isinstance(payload, Mapping):
        return None
    section_id = _text(payload.get("id"))
    paper_id = _text(payload.get("paperId"))
    title = _text(payload.get("title"))
    text_excerpt = _text(payload.get("textExcerpt"))
    section_type = _text(payload.get("sectionType")) or "unknown"
    if not section_id or not paper_id or not title or not text_excerpt:
        return None
    return PaperSection(
        id=section_id,
        paperId=paper_id,
        title=title,
        level=_positive_int(payload.get("level")) or 1,
        pageStart=_positive_int(payload.get("pageStart")),
        pageEnd=_positive_int(payload.get("pageEnd")),
        textExcerpt=text_excerpt,
        summary=_optional_text(payload.get("summary")),
        sectionType=section_type,
    )


def _quality_from_payload(payload: Any, *, paper_id: str) -> PaperReaderQuality | None:
    if not isinstance(payload, Mapping) or _text(payload.get("paperId")) != paper_id:
        return None
    return PaperReaderQuality(
        paperId=paper_id,
        pdfAvailable=bool(payload.get("pdfAvailable")),
        textExtracted=bool(payload.get("textExtracted")),
        summaryAvailable=bool(payload.get("summaryAvailable")),
        implementationVerified=bool(payload.get("implementationVerified")),
        benchmarkVerified=bool(payload.get("benchmarkVerified")),
        evidenceCoverage=max(0.0, min(_float_number(payload.get("evidenceCoverage")) or 0.0, 1.0)),
        lastUpdatedAt=_optional_text(payload.get("lastUpdatedAt")),
    )


def _mapping_list(value: Any) -> list[Mapping[str, Any]]:
    items: list[Mapping[str, Any]] = []
    for item in _sequence(value):
        sanitized = sanitize_public_payload(item)
        if isinstance(sanitized, Mapping):
            items.append(sanitized)
    return items


def _paper_payload(raw_paper: Any) -> PublicPaper | None:
    if not isinstance(raw_paper, Mapping):
        return None

    paper_id = _text(raw_paper.get("id"))
    title = _text(raw_paper.get("title"))
    abstract = _text(raw_paper.get("abstractSnippet")) or _text(raw_paper.get("summary"))
    paper_url = _text(raw_paper.get("paperUrl")) or _text(raw_paper.get("url"))
    if not paper_id or not title or not abstract or not paper_url:
        return None

    repo_url = _paper_repo_url(raw_paper, abstract)
    github_stars = _int_number(raw_paper.get("githubStars"))
    implementations = tuple(_implementations(raw_paper, repo_url=repo_url, github_stars=github_stars))
    paper = PublicPaper(
        id=paper_id,
        slug=_text(raw_paper.get("slug")) or paper_id,
        title=title,
        titleZh=_optional_text(raw_paper.get("titleZh")),
        abstractSnippet=abstract,
        abstractSnippetZh=_optional_text(raw_paper.get("abstractSnippetZh")),
        authors=tuple(_string_list(raw_paper.get("authors"))),
        publishedAt=_text(raw_paper.get("publishedAt")) or _text(raw_paper.get("published_at")),
        venue=_optional_text(raw_paper.get("venue")) or "arXiv",
        citationCount=_int_number(raw_paper.get("citationCount")),
        citationDoi=_optional_text(raw_paper.get("citationDoi")) or _optional_text(raw_paper.get("doi")),
        githubMomentum=_float_number(raw_paper.get("githubMomentum")),
        githubStars=github_stars,
        thumbnailUrl=_optional_text(raw_paper.get("thumbnailUrl")),
        arxivId=_optional_text(raw_paper.get("arxivId")) or _arxiv_id_from_url(_text(raw_paper.get("arxivUrl")) or paper_url),
        tags=tuple(_string_list(raw_paper.get("tags"))),
        taskRefs=tuple(_refs(raw_paper.get("taskRefs"))),
        methodRefs=tuple(_refs(raw_paper.get("methodRefs"))),
        paperUrl=paper_url.replace("http://", "https://", 1),
        arxivUrl=_normalized_https_url(raw_paper.get("arxivUrl")),
        pdfUrl=_normalized_https_url(raw_paper.get("pdfUrl")),
        repoUrl=repo_url,
        projectUrl=_normalized_https_url(raw_paper.get("projectUrl")),
        isPublished=raw_paper.get("isPublished") is not False,
        implementations=implementations,
        benchmarks=tuple(_benchmarks(raw_paper)),
        evidenceRefs=tuple(_mapping_refs(raw_paper.get("evidenceRefs") or raw_paper.get("evidence_refs"))),
        sourceRefs=tuple(_mapping_refs(raw_paper.get("sourceRefs") or raw_paper.get("source_refs"))),
    )
    return _with_heat_score(paper)


def _with_heat_score(paper: PublicPaper) -> PublicPaper:
    recency = _recency_score(paper.publishedAt)
    github = (paper.githubStars or 0) ** 0.5
    citations = (paper.citationCount or 0) ** 0.5
    heat = round(github * 4 + citations * 6 + recency * 25, 2)
    return PublicPaper(**(paper.__dict__ | {"newsroomHeatScore": heat}))


def _with_summary(paper: PublicPaper, summary: PaperAISummary | None) -> PublicPaper:
    return PublicPaper(**(paper.__dict__ | {"aiSummary": summary}))


def _paper_graph_payload(reader: PaperReaderPayload) -> Mapping[str, Any]:
    paper = reader.paper
    nodes: list[dict[str, Any]] = [
        {
            "id": f"paper:{paper.id}",
            "type": "paper",
            "label": paper.title,
            "paperId": paper.id,
            "slug": paper.slug,
            "url": paper.paperUrl,
        }
    ]
    edges: list[dict[str, Any]] = []

    def add_node_edge(kind: str, item: Mapping[str, Any], label_key: str = "title") -> None:
        item_id = _text(item.get("id"))
        label = _text(item.get(label_key)) or _text(item.get("name"))
        if not item_id or not label:
            return
        node_id = f"{kind}:{item_id}"
        node: dict[str, Any] = {
            "id": node_id,
            "type": kind,
            "label": label,
        }
        for key in ("slug", "url", "sourceType", "score"):
            value = item.get(key)
            if value not in (None, "", []):
                node[key] = value
        nodes.append(node)
        edges.append(
            {
                "id": f"paper:{paper.id}->{node_id}",
                "source": f"paper:{paper.id}",
                "target": node_id,
                "type": "related",
                "relationReason": _text(item.get("relationReason")) or "Related signal",
                "score": _float_number(item.get("score")) or 0,
            }
        )

    for item in reader.relatedPapers:
        add_node_edge("paper", item)
    for item in reader.relatedProjects:
        add_node_edge("project", item, label_key="name")
    for item in reader.relatedNews:
        add_node_edge("news", item)

    return sanitize_public_payload({"paperId": paper.id, "nodes": nodes, "edges": edges})


def _task_index(papers: Sequence[PublicPaper]) -> list[Mapping[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for paper in papers:
        for task in paper.taskRefs:
            record = records.setdefault(
                task.slug,
                {
                    "id": task.id,
                    "slug": task.slug,
                    "name": task.name,
                    "nameZh": task.nameZh,
                    "group": _task_group(task),
                    "paperIds": set(),
                    "methodRefs": {},
                    "sisterTasks": {},
                    "benchmarkIds": set(),
                },
            )
            record["paperIds"].add(paper.id)
            for method in paper.methodRefs:
                record["methodRefs"][method.slug] = method
            for sibling in paper.taskRefs:
                if sibling.slug != task.slug:
                    record["sisterTasks"][sibling.slug] = sibling
            for benchmark in paper.benchmarks:
                if not benchmark.taskSlug or benchmark.taskSlug == task.slug:
                    record["benchmarkIds"].add(benchmark.id)

    results: list[Mapping[str, Any]] = []
    for record in records.values():
        paper_count = len(record["paperIds"])
        methods = _top_refs(record["methodRefs"].values())
        siblings = _top_refs(record["sisterTasks"].values())
        payload = {
            "id": record["id"],
            "slug": record["slug"],
            "name": record["name"],
            "group": record["group"],
            "description": f"Derived from {paper_count} public papers tagged with {record['name']}.",
            "paperCount": paper_count,
            "benchmarkCount": len(record["benchmarkIds"]),
            "methodCount": len(record["methodRefs"]),
            "sisterTasks": [ref.to_dict() for ref in siblings],
            "commonMethods": [ref.to_dict() for ref in methods],
        }
        if record.get("nameZh"):
            payload["nameZh"] = record["nameZh"]
        results.append(payload)
    return sorted(results, key=lambda item: (-int(item["paperCount"]), str(item["name"]).casefold()))


def _method_index(papers: Sequence[PublicPaper]) -> list[Mapping[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for paper in papers:
        for method in paper.methodRefs:
            record = records.setdefault(
                method.slug,
                {
                    "id": method.id,
                    "slug": method.slug,
                    "name": method.name,
                    "nameZh": method.nameZh,
                    "area": method.area,
                    "paperIds": set(),
                    "taskRefs": {},
                    "relatedMethods": {},
                    "benchmarkRefs": {},
                    "implementationIds": set(),
                },
            )
            if method.area and not record.get("area"):
                record["area"] = method.area
            record["paperIds"].add(paper.id)
            for task in paper.taskRefs:
                record["taskRefs"][task.slug] = task
            for sibling in paper.methodRefs:
                if sibling.slug != method.slug:
                    record["relatedMethods"][sibling.slug] = sibling
            for benchmark in paper.benchmarks:
                record["benchmarkRefs"][benchmark.id] = benchmark
            for implementation in paper.implementations:
                record["implementationIds"].add(implementation.id)

    results: list[Mapping[str, Any]] = []
    for record in records.values():
        paper_count = len(record["paperIds"])
        tasks = _top_refs(record["taskRefs"].values())
        related_methods = _top_refs(record["relatedMethods"].values())
        payload = {
            "id": record["id"],
            "slug": record["slug"],
            "name": record["name"],
            "description": f"Derived from {paper_count} public papers using {record['name']}.",
            "paperCount": paper_count,
            "taskCount": len(record["taskRefs"]),
            "implementationCount": len(record["implementationIds"]),
            "area": record.get("area") or _method_area(record["name"]),
            "relatedTasks": [ref.to_dict() for ref in tasks],
            "relatedMethods": [ref.to_dict() for ref in related_methods],
            "commonBenchmarks": [_benchmark_ref(benchmark) for benchmark in list(record["benchmarkRefs"].values())[:8]],
        }
        if record.get("nameZh"):
            payload["nameZh"] = record["nameZh"]
        results.append(payload)
    return sorted(results, key=lambda item: (-int(item["paperCount"]), str(item["name"]).casefold()))


def _top_refs(refs: Sequence[PaperRef]) -> list[PaperRef]:
    return sorted(refs, key=lambda ref: ref.name.casefold())[:8]


def _benchmark_ref(benchmark: PaperBenchmarkResult) -> Mapping[str, Any]:
    slug = _slugify(benchmark.name) or benchmark.id
    payload = {"id": benchmark.id, "slug": slug, "name": benchmark.name}
    if benchmark.category:
        payload["category"] = benchmark.category
    return payload


def _labelled_values(label: str, values: Sequence[str]) -> str:
    cleaned = [value for value in (_text(item) for item in values) if value]
    return f"{label}: {', '.join(cleaned)}." if cleaned else ""


def _join_sentences(values: Sequence[str]) -> str:
    return " ".join(value for value in (_text(item) for item in values) if value)


def _drop_empty(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in (None, "", [], {})}


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _task_group(task: PaperRef) -> str:
    normalized = normalize_ai_task_group(task.group)
    if normalized:
        return normalized
    text = f"{task.slug} {task.name}".casefold()
    if any(term in text for term in ("agent", "tool", "computer use", "browser")):
        return "agents"
    if any(term in text for term in ("language", "llm", "modeling", "instruction")):
        return "language-models"
    if any(term in text for term in ("reasoning", "math", "logic", "qa", "question answering")):
        return "reasoning"
    if any(term in text for term in ("multimodal", "vision-language", "vqa", "document")):
        return "multimodal"
    if any(term in text for term in ("vision", "visual", "image", "segmentation", "detection")):
        return "computer-vision"
    if any(term in text for term in ("serving", "inference", "kernel", "infra", "systems")):
        return "systems-infra"
    if any(term in text for term in ("audio", "speech")):
        return "speech-audio"
    if any(term in text for term in ("robot", "robotics")):
        return "robotics-embodied"
    if any(term in text for term in ("code", "software", "program")):
        return "code-ai"
    if any(term in text for term in ("retrieval", "rag", "knowledge")):
        return "retrieval-knowledge"
    if any(term in text for term in ("evaluation", "benchmark", "data")):
        return "data-evaluation"
    if any(term in text for term in ("safety", "security", "privacy", "alignment")):
        return "security-safety"
    if any(term in text for term in ("science", "medical", "bio", "chem")):
        return "ai-for-science"
    if any(term in text for term in ("human", "interaction", "interface")):
        return "human-ai-interaction"
    return "agents"


def _method_area(name: str) -> str:
    normalized = normalize_method_collection(name)
    if normalized:
        return normalized
    text = name.casefold()
    if any(term in text for term in ("vision", "visual", "image", "multimodal")):
        return normalize_method_collection("Vision Transformers") or "Transformers"
    if any(term in text for term in ("serving", "kernel", "inference")):
        return normalize_method_collection("Optimization") or "Language Models"
    if any(term in text for term in ("agent", "tool", "planning", "react")):
        return normalize_method_collection("Prompt Engineering") or "Language Models"
    if any(term in text for term in ("language", "llm", "reasoning", "thought")):
        return normalize_method_collection("Language Models") or "Transformers"
    return normalize_method_collection("Transformers") or "Language Models"


def _benchmark_category(value: Any, *, name: str, task_slug: str | None) -> str | None:
    normalized = normalize_benchmark_category(value)
    if normalized:
        return normalized
    text = f"{name} {task_slug or ''}".casefold()
    if any(term in text for term in ("swe", "human_eval", "humaneval", "code", "software")):
        return "software-engineering" if "swe" in text or "software" in text else "code-generation"
    if any(term in text for term in ("mmlu", "glue", "superglue", "understanding")):
        return "language-understanding"
    if any(term in text for term in ("qa", "question", "hotpot", "squad", "natural questions")):
        return "question-answering"
    if any(term in text for term in ("math", "gsm", "mmlu-pro")):
        return "reasoning-math"
    if any(term in text for term in ("logic", "proof", "game of 24")):
        return "reasoning-logic"
    if any(term in text for term in ("long", "context", "needle")):
        return "long-context"
    if any(term in text for term in ("agent", "webarena", "task completion")):
        return "agent-task-completion"
    if any(term in text for term in ("tool", "api")):
        return "tool-use"
    if any(term in text for term in ("retrieval", "search", "rag")):
        return "retrieval-search"
    if any(term in text for term in ("vqa", "visual question")):
        return "visual-question-answering"
    if any(term in text for term in ("image", "imagenet", "classification")):
        return "image-classification"
    if any(term in text for term in ("detection", "coco")):
        return "object-detection"
    if any(term in text for term in ("segment", "mask", "sam")):
        return "segmentation"
    if any(term in text for term in ("video", "activity")):
        return "video-understanding"
    if any(term in text for term in ("speech", "asr", "whisper")):
        return "speech-recognition"
    if any(term in text for term in ("audio", "music")):
        return "audio-understanding"
    if any(term in text for term in ("robot", "manipulation")):
        return "robotics-manipulation"
    if any(term in text for term in ("medical", "med", "biomedical")):
        return "medical-imaging"
    if any(term in text for term in ("safety", "robust", "adversarial")):
        return "safety-robustness"
    if any(term in text for term in ("privacy", "security")):
        return "privacy-security"
    if any(term in text for term in ("efficiency", "latency", "throughput")):
        return "efficiency-systems"
    return None


def _copy_summary(summary: PaperAISummary, *, cached: bool) -> PaperAISummary:
    return PaperAISummary(**(summary.__dict__ | {"cached": cached}))


def _implementations(
    raw_paper: Mapping[str, Any],
    *,
    repo_url: str | None,
    github_stars: int | None,
) -> list[PaperImplementation]:
    implementations: list[PaperImplementation] = []
    for index, value in enumerate(_sequence(raw_paper.get("implementations"))):
        if not isinstance(value, Mapping):
            continue
        implementation_repo = _normalize_github_repo_url(
            _text(value.get("repoUrl")) or _text(value.get("githubUrl")) or _text(value.get("url"))
        )
        if implementation_repo is None:
            continue
        implementations.append(
            PaperImplementation(
                id=_text(value.get("id")) or f"implementation-{index + 1}",
                name=_text(value.get("name")) or _repo_name(implementation_repo),
                repoUrl=implementation_repo,
                provider=_text(value.get("provider")) or "github",
                githubStars=_int_number(value.get("githubStars")),
            )
        )
    if repo_url and not any(item.repoUrl == repo_url for item in implementations):
        implementations.insert(
            0,
            PaperImplementation(
                id="primary-repository",
                name=_repo_name(repo_url),
                repoUrl=repo_url,
                githubStars=github_stars,
            ),
        )
    return implementations


def _benchmarks(raw_paper: Mapping[str, Any]) -> list[PaperBenchmarkResult]:
    results: list[PaperBenchmarkResult] = []
    raw_results = _sequence(raw_paper.get("benchmarks")) or _sequence(raw_paper.get("benchmarkResults"))
    for index, value in enumerate(raw_results):
        if not isinstance(value, Mapping):
            continue
        name = _text(value.get("name")) or _text(value.get("benchmark"))
        if not name:
            continue
        results.append(
            PaperBenchmarkResult(
                id=_text(value.get("id")) or _text(value.get("slug")) or f"benchmark-{index + 1}",
                name=name,
                category=_benchmark_category(
                    value.get("category") or value.get("benchmarkCategory") or value.get("benchmark_category"),
                    name=name,
                    task_slug=_optional_text(value.get("taskSlug") or value.get("task_slug")),
                ),
                metric=_optional_text(value.get("metric")),
                value=value.get("value") if isinstance(value.get("value"), (str, int, float)) else value.get("bestValue"),
                taskSlug=_optional_text(value.get("taskSlug") or value.get("task_slug")),
                url=_normalized_https_url(value.get("url")),
                confidence=_float_number(value.get("confidence")),
                evidence=_optional_text(value.get("evidence") or value.get("evidenceSummary")),
            )
        )
    return results


def _sort_papers(papers: list[PublicPaper], sort: PaperSort) -> list[PublicPaper]:
    if sort == "newest":
        return sorted(papers, key=lambda paper: _timestamp(paper.publishedAt), reverse=True)
    if sort == "most_cited":
        return sorted(papers, key=lambda paper: paper.citationCount or -1, reverse=True)
    return sorted(papers, key=lambda paper: paper.newsroomHeatScore or 0, reverse=True)


def _matches_period(paper: PublicPaper, period: PaperPeriod, *, now: datetime) -> bool:
    if period == "all":
        return True
    published = _datetime(paper.publishedAt)
    if published is None:
        return False
    if period == "daily":
        return published >= now - timedelta(days=1)
    if period == "weekly":
        return published >= now - timedelta(days=7)
    return published >= now - timedelta(days=30)


def _recency_score(value: str) -> float:
    published = _datetime(value)
    if published is None:
        return 0
    days = max((datetime.now(timezone.utc) - published).days, 0)
    return max(0.0, 1.0 - min(days, 365) / 365)


def _paper_search_text(paper: PublicPaper) -> str:
    parts = [
        paper.title,
        paper.abstractSnippet,
        " ".join(paper.authors),
        " ".join(paper.tags),
        " ".join(ref.name for ref in paper.taskRefs),
        " ".join(ref.slug for ref in paper.taskRefs),
        " ".join(ref.group or "" for ref in paper.taskRefs),
        " ".join(ref.name for ref in paper.methodRefs),
        " ".join(ref.slug for ref in paper.methodRefs),
        " ".join(ref.area or "" for ref in paper.methodRefs),
    ]
    return " ".join(parts).casefold()


def _summary_request(paper: PublicPaper, *, locale: PaperLocale) -> LLMRequest:
    language = "Chinese" if locale == "zh" else "English"
    public_context = _summary_public_context(paper)
    return LLMRequest(
        messages=[
            LLMMessage.system(
                "You write concise, evidence-oriented research summaries for NewsRoom. "
                "Use only the provided public paper signals. Return strict JSON with keys: "
                "summary, keyInsights, limitations, contributions, methodSummary, "
                "experimentSummary, engineeringRelevance, readingDifficulty, recommendedAudience. "
                "readingDifficulty must be one of low, medium, high. Omit fields when evidence is missing."
            ),
            LLMMessage.user(
                f"Language: {language}\n"
                f"Public paper context JSON:\n{json.dumps(public_context, ensure_ascii=False, sort_keys=True)}\n"
                "Write one paragraph summary, up to 3 keyInsights, up to 3 contributions, "
                "1-2 limitations, and concise method/experiment/engineering relevance fields when supported."
            ),
        ],
        temperature=0.2,
        max_tokens=1000,
        response_format={"type": "json_object"},
        metadata={"paper_id": paper.id, "locale": locale, "summary_schema_version": PAPER_SUMMARY_SCHEMA_VERSION},
    )


def _parse_summary_response(content: str) -> Mapping[str, Any]:
    stripped = content.strip()
    if not stripped:
        return {}
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return {"summary": stripped}
    return payload if isinstance(payload, Mapping) else {"summary": stripped}


def _fallback_summary(
    paper: PublicPaper,
    *,
    locale: PaperLocale,
    route: str,
    generated_at: datetime,
) -> PaperAISummary:
    task_names = [ref.name for ref in paper.taskRefs[:3]]
    method_names = [ref.name for ref in paper.methodRefs[:3]]
    implementation_names = [implementation.name for implementation in paper.implementations[:2]]
    benchmark_names = [benchmark.name for benchmark in paper.benchmarks[:3]]
    summary = _fallback_summary_text(
        paper,
        locale=locale,
        task_names=task_names,
        method_names=method_names,
        implementation_names=implementation_names,
        benchmark_names=benchmark_names,
    )
    return PaperAISummary(
        paperId=paper.id,
        locale=locale,
        modelRoute=route,
        abstractHash=paper_abstract_hash(paper),
        summary=summary,
        keyInsights=tuple(_fallback_key_insights(paper, locale=locale, task_names=task_names, method_names=method_names)),
        limitations=tuple(_fallback_limitations(paper, locale=locale)),
        contributions=tuple(_fallback_contributions(paper, locale=locale, method_names=method_names)),
        methodSummary=_fallback_method_summary(paper, locale=locale, method_names=method_names),
        experimentSummary=_fallback_experiment_summary(paper, locale=locale, benchmark_names=benchmark_names),
        engineeringRelevance=_fallback_engineering_relevance(paper, locale=locale, implementation_names=implementation_names),
        readingDifficulty="medium",
        recommendedAudience=tuple(_fallback_audience(locale=locale, task_names=task_names)),
        summarySchemaVersion=PAPER_SUMMARY_SCHEMA_VERSION,
        generatedAt=generated_at.isoformat().replace("+00:00", "Z"),
        cached=False,
    )


def _fallback_summary_text(
    paper: PublicPaper,
    *,
    locale: PaperLocale,
    task_names: Sequence[str],
    method_names: Sequence[str],
    implementation_names: Sequence[str],
    benchmark_names: Sequence[str],
) -> str:
    abstract = _first_sentence(paper.abstractSnippet) or paper.abstractSnippet
    if locale == "zh":
        parts = [f"{paper.title} 是一篇来自 {paper.venue or '公开论文源'} 的研究论文。"]
        if abstract:
            parts.append(f"论文摘要显示：{abstract}")
        if task_names:
            parts.append(f"当前归类任务包括：{', '.join(task_names)}。")
        if method_names:
            parts.append(f"方法信号包括：{', '.join(method_names)}。")
        if implementation_names:
            parts.append(f"已关联实现：{', '.join(implementation_names)}。")
        if benchmark_names:
            parts.append(f"已提取基准：{', '.join(benchmark_names)}。")
        return " ".join(parts)

    parts = [f"{paper.title} is a research paper from {paper.venue or 'a public paper source'}."]
    if abstract:
        parts.append(f"The abstract says: {abstract}")
    if task_names:
        parts.append(f"Current task labels include {', '.join(task_names)}.")
    if method_names:
        parts.append(f"Method signals include {', '.join(method_names)}.")
    if implementation_names:
        parts.append(f"Linked implementations include {', '.join(implementation_names)}.")
    if benchmark_names:
        parts.append(f"Extracted benchmarks include {', '.join(benchmark_names)}.")
    return " ".join(parts)


def _fallback_key_insights(
    paper: PublicPaper,
    *,
    locale: PaperLocale,
    task_names: Sequence[str],
    method_names: Sequence[str],
) -> list[str]:
    if locale == "zh":
        insights = [
            f"论文主题来自真实缓存的标题、摘要和 arXiv/论文元数据：{paper.title}。",
        ]
        if task_names:
            insights.append(f"已归入任务方向：{', '.join(task_names)}。")
        if method_names:
            insights.append(f"已识别方法方向：{', '.join(method_names)}。")
        return insights[:3]
    insights = [
        f"The summary is grounded in the cached title, abstract, and public paper metadata for {paper.title}.",
    ]
    if task_names:
        insights.append(f"Task taxonomy signals: {', '.join(task_names)}.")
    if method_names:
        insights.append(f"Method taxonomy signals: {', '.join(method_names)}.")
    return insights[:3]


def _fallback_limitations(paper: PublicPaper, *, locale: PaperLocale) -> list[str]:
    missing = []
    if not paper.taskRefs:
        missing.append("task taxonomy")
    if not paper.methodRefs:
        missing.append("method taxonomy")
    if not paper.benchmarks:
        missing.append("benchmark extraction")
    if locale == "zh":
        if missing:
            return [f"本地摘要缺少完整的 {', '.join(missing)} 信号，应该在模型恢复后刷新。"]
        return ["这是模型不可用时的本地降级摘要，细粒度分析应在模型恢复后刷新。"]
    if missing:
        return [f"This local fallback lacks complete {', '.join(missing)} signals and should be refreshed when the model route recovers."]
    return ["This is a local fallback summary; refresh it when the model route is available for finer analysis."]


def _fallback_contributions(
    paper: PublicPaper,
    *,
    locale: PaperLocale,
    method_names: Sequence[str],
) -> list[str]:
    if method_names:
        if locale == "zh":
            return [f"论文贡献与这些方法信号相关：{', '.join(method_names)}。"]
        return [f"The paper's contribution is associated with these method signals: {', '.join(method_names)}."]
    abstract = _first_sentence(paper.abstractSnippet)
    if abstract:
        return [abstract]
    return []


def _fallback_method_summary(paper: PublicPaper, *, locale: PaperLocale, method_names: Sequence[str]) -> str | None:
    if method_names:
        if locale == "zh":
            return f"方法摘要来自已发布 taxonomy：{', '.join(method_names)}。"
        return f"Method summary from published taxonomy: {', '.join(method_names)}."
    return None


def _fallback_experiment_summary(paper: PublicPaper, *, locale: PaperLocale, benchmark_names: Sequence[str]) -> str | None:
    if benchmark_names:
        if locale == "zh":
            return f"已提取实验/基准信号：{', '.join(benchmark_names)}。"
        return f"Extracted experiment or benchmark signals: {', '.join(benchmark_names)}."
    return None


def _fallback_engineering_relevance(
    paper: PublicPaper,
    *,
    locale: PaperLocale,
    implementation_names: Sequence[str],
) -> str | None:
    if implementation_names:
        if locale == "zh":
            return f"工程相关性来自已关联代码实现：{', '.join(implementation_names)}。"
        return f"Engineering relevance is supported by linked implementations: {', '.join(implementation_names)}."
    if paper.repoUrl:
        if locale == "zh":
            return f"论文提供了代码仓库：{paper.repoUrl}。"
        return f"The paper provides a code repository: {paper.repoUrl}."
    return None


def _fallback_audience(*, locale: PaperLocale, task_names: Sequence[str]) -> list[str]:
    if locale == "zh":
        if task_names:
            return [f"关注 {', '.join(task_names[:2])} 的研究和工程读者"]
        return ["需要快速了解论文主题的研究和工程读者"]
    if task_names:
        return [f"Researchers and engineers tracking {', '.join(task_names[:2])}"]
    return ["Researchers and engineers who need a quick paper overview"]


def _first_sentence(value: str, *, max_chars: int = 360) -> str:
    text = " ".join(value.split())
    if not text:
        return ""
    match = re.search(r"(?<=[.!?。！？])\s+", text)
    sentence = text[: match.start()].strip() if match else text
    if len(sentence) <= max_chars:
        return sentence
    return sentence[: max_chars - 1].rstrip() + "..."


def _summary_public_context(paper: PublicPaper) -> Mapping[str, Any]:
    context = {
        "title": paper.title,
        "authors": list(paper.authors),
        "venue": paper.venue,
        "publishedAt": paper.publishedAt,
        "abstract": paper.abstractSnippet,
        "tasks": [ref.to_dict() for ref in paper.taskRefs],
        "methods": [ref.to_dict() for ref in paper.methodRefs],
        "implementations": [implementation.to_dict() for implementation in paper.implementations],
        "benchmarks": [benchmark.to_dict() for benchmark in paper.benchmarks],
        "sections": [
            {"title": "Abstract", "sectionType": "abstract", "textExcerpt": paper.abstractSnippet},
            _summary_signal_section("Method signals", "method", _summary_method_signal_text(paper)),
            _summary_signal_section("Experiment signals", "experiment", _summary_experiment_signal_text(paper)),
            _summary_signal_section("Implementation signals", "implementation", _summary_implementation_signal_text(paper)),
        ],
        "evidenceRefs": [sanitize_public_payload(ref) for ref in paper.evidenceRefs],
        "sourceRefs": [sanitize_public_payload(ref) for ref in paper.sourceRefs],
    }
    return sanitize_public_payload(_drop_empty(context))


def _summary_signal_section(title: str, section_type: str, text: str) -> Mapping[str, Any]:
    return _drop_empty({"title": title, "sectionType": section_type, "textExcerpt": text})


def _summary_method_signal_text(paper: PublicPaper) -> str:
    return _join_sentences(
        [
            _labelled_values("Tasks", [ref.name for ref in paper.taskRefs]),
            _labelled_values("Methods", [ref.name for ref in paper.methodRefs]),
        ]
    )


def _summary_experiment_signal_text(paper: PublicPaper) -> str:
    lines = []
    for benchmark in paper.benchmarks:
        parts = [
            benchmark.name,
            benchmark.metric or "",
            str(benchmark.value) if benchmark.value is not None else "",
            benchmark.taskSlug or "",
            benchmark.category or "",
        ]
        line = " / ".join(part for part in parts if part)
        if line:
            lines.append(line)
    return "\n".join(lines)


def _summary_implementation_signal_text(paper: PublicPaper) -> str:
    lines = []
    for implementation in paper.implementations:
        parts = [implementation.name, implementation.repoUrl]
        if implementation.githubStars is not None:
            parts.append(f"{implementation.githubStars} GitHub stars")
        lines.append(" / ".join(part for part in parts if part))
    return "\n".join(lines)


def _summary_from_payload(payload: Mapping[str, Any]) -> PaperAISummary | None:
    sanitized = sanitize_public_payload(payload)
    if not isinstance(sanitized, Mapping):
        return None
    paper_id = _text(sanitized.get("paperId"))
    locale = _text(sanitized.get("locale"))
    route = _text(sanitized.get("modelRoute"))
    abstract_hash = _text(sanitized.get("abstractHash"))
    summary = _text(sanitized.get("summary"))
    if not paper_id or locale not in {"zh", "en"} or not route or not abstract_hash or not summary:
        return None
    return PaperAISummary(
        paperId=paper_id,
        locale=locale,  # type: ignore[arg-type]
        modelRoute=route,
        abstractHash=abstract_hash,
        summary=summary,
        keyInsights=tuple(_string_list(sanitized.get("keyInsights") or sanitized.get("key_insights"))),
        limitations=tuple(_string_list(sanitized.get("limitations"))),
        contributions=tuple(_string_list(sanitized.get("contributions"))),
        methodSummary=_optional_text(sanitized.get("methodSummary") or sanitized.get("method_summary")),
        experimentSummary=_optional_text(sanitized.get("experimentSummary") or sanitized.get("experiment_summary")),
        engineeringRelevance=_optional_text(sanitized.get("engineeringRelevance") or sanitized.get("engineering_relevance")),
        readingDifficulty=_reading_difficulty(
            sanitized.get("readingDifficulty") or sanitized.get("reading_difficulty")
        ),
        recommendedAudience=tuple(_string_list(sanitized.get("recommendedAudience") or sanitized.get("recommended_audience"))),
        summarySchemaVersion=_optional_text(sanitized.get("summarySchemaVersion") or sanitized.get("summary_schema_version")),
        generatedAt=_text(sanitized.get("generatedAt")),
        cached=True,
    )


def _papers_data_path(configured_path: str | Path | None) -> Path:
    if configured_path is not None:
        return Path(configured_path).expanduser().resolve()
    env_path = os.environ.get(PAPERS_DATA_PATH_ENV)
    if env_path:
        return Path(env_path).expanduser().resolve()
    return _project_root() / ".newsroom" / "papers" / "arxiv-papers.json"


def _summary_cache_path(configured_path: str | Path | None) -> Path:
    if configured_path is not None:
        return Path(configured_path).expanduser().resolve()
    env_path = os.environ.get(PAPERS_SUMMARY_CACHE_PATH_ENV)
    if env_path:
        return Path(env_path).expanduser().resolve()
    return _project_root() / ".newsroom" / "papers" / "ai-summaries.json"


def _summary_events_path(configured_path: str | Path | None) -> Path:
    if configured_path is not None:
        return Path(configured_path).expanduser().resolve()
    env_path = os.environ.get(PAPERS_SUMMARY_EVENTS_PATH_ENV)
    if env_path:
        return Path(env_path).expanduser().resolve()
    return _project_root() / ".newsroom" / "papers" / "summary-events.jsonl"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _paper_repo_url(raw_paper: Mapping[str, Any], abstract: str) -> str | None:
    explicit_repo = _normalize_github_repo_url(_text(raw_paper.get("repoUrl")))
    if explicit_repo:
        return explicit_repo
    for value in (
        _text(raw_paper.get("githubUrl")),
        _text(raw_paper.get("github_url")),
        _text(raw_paper.get("codeUrl")),
        _text(raw_paper.get("code_url")),
        abstract,
    ):
        repo_url = _extract_github_repo_url(value)
        if repo_url:
            return repo_url
    return None


def _extract_github_repo_url(value: str) -> str | None:
    match = _GITHUB_REPO_PATTERN.search(value)
    return _normalize_github_repo_url(match.group(0)) if match else None


def _normalize_github_repo_url(value: str) -> str | None:
    text = value.strip().rstrip(".,;:)]}>'\"")
    if not text:
        return None
    try:
        from urllib.parse import urlparse

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


def _repo_name(value: str) -> str:
    try:
        from urllib.parse import urlparse

        parts = [part for part in urlparse(value).path.split("/") if part]
    except ValueError:
        parts = []
    return "/".join(parts[:2]) or "GitHub repository"


def _refs(value: Any) -> list[PaperRef]:
    refs: list[PaperRef] = []
    for item in _sequence(value):
        if not isinstance(item, Mapping):
            continue
        ref_id = _text(item.get("id"))
        slug = _text(item.get("slug"))
        name = _text(item.get("name"))
        if ref_id and slug and name:
            refs.append(
                PaperRef(
                    id=ref_id,
                    slug=slug,
                    name=name,
                    nameZh=_optional_text(item.get("nameZh")),
                    group=normalize_ai_task_group(item.get("group")),
                    area=normalize_method_collection(item.get("area")),
                    confidence=_float_number(item.get("confidence")),
                    evidence=_optional_text(item.get("evidence") or item.get("evidenceSummary")),
                )
            )
    return refs


def _mapping_refs(value: Any) -> list[Mapping[str, Any]]:
    refs: list[Mapping[str, Any]] = []
    for item in _sequence(value):
        if isinstance(item, Mapping):
            cleaned = sanitize_public_payload(item)
            if isinstance(cleaned, Mapping):
                refs.append(cleaned)
    return refs


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return [_text(item) for item in _sequence(value) if _text(item)]


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _reading_difficulty(value: Any) -> Literal["low", "medium", "high"] | None:
    text = _text(value).casefold()
    if text in {"low", "medium", "high"}:
        return text  # type: ignore[return-value]
    return None


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _int_number(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _positive_int(value: Any) -> int | None:
    number = _int_number(value)
    return number if number is not None and number >= 0 else None


def _float_number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _normalized_https_url(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    try:
        from urllib.parse import urlparse

        parsed = urlparse(text.replace("http://", "https://", 1))
    except ValueError:
        return None
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    return parsed.geturl()


def _arxiv_id_from_url(value: str) -> str | None:
    if not value:
        return None
    match = re.search(r"arxiv\.org/(?:abs|pdf)/([^/?#]+)", value, flags=re.IGNORECASE)
    return match.group(1).removesuffix(".pdf").removesuffix("v1") if match else None


def _timestamp(value: str) -> float:
    parsed = _datetime(value)
    return parsed.timestamp() if parsed is not None else 0.0


def _datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
