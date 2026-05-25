from __future__ import annotations

import hashlib
import json
import os
import re
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


PaperPeriod = Literal["daily", "weekly", "monthly", "all"]
PaperSort = Literal["trending", "newest", "most_cited"]
PaperLocale = Literal["zh", "en"]

PAPERS_DATA_PATH_ENV = "NEWSROOM_PAPERS_DATA_PATH"
PAPERS_SUMMARY_CACHE_PATH_ENV = "NEWSROOM_PAPERS_AI_SUMMARY_CACHE_PATH"
PAPERS_SUMMARY_MODEL_ROUTE_ENV = "NEWS_PAPERS_SUMMARY_MODEL_ROUTE"
DEFAULT_LIMIT = 1000
MAX_LIMIT = 5000

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

    def to_dict(self) -> dict[str, Any]:
        payload = {"id": self.id, "slug": self.slug, "name": self.name}
        if self.nameZh:
            payload["nameZh"] = self.nameZh
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
    metric: str | None = None
    value: str | int | float | None = None
    taskSlug: str | None = None
    url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"id": self.id, "name": self.name}
        if self.metric is not None:
            payload["metric"] = self.metric
        if self.value is not None:
            payload["value"] = self.value
        if self.taskSlug is not None:
            payload["taskSlug"] = self.taskSlug
        if self.url is not None:
            payload["url"] = self.url
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
    generatedAt: str = ""
    cached: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
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
        llm_client_factory: Callable[[str], Any] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.papers_data_path = _papers_data_path(papers_data_path)
        self.summary_cache_path = _summary_cache_path(summary_cache_path)
        self.llm_client_factory = llm_client_factory or _default_llm_client_factory
        self.clock = clock or (lambda: datetime.now(timezone.utc))

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

    def get_or_generate_summary(self, paper_id: str, *, locale: PaperLocale) -> PaperAISummary:
        paper = self.get_paper(paper_id)
        route = self._summary_route()
        cached = self._cached_summary_for(paper, route, locale=locale)
        if cached is not None:
            return _copy_summary(cached, cached=True)

        summary = self._generate_summary(paper, locale=locale, route=route)
        cache = self._read_summary_cache()
        cache[summary_cache_key(paper, locale=locale, route=route)] = summary.to_dict() | {"cached": False}
        self._write_summary_cache(cache)
        return summary

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
            generatedAt=self.clock().isoformat().replace("+00:00", "Z"),
            cached=False,
        )

    def _read_summary_cache(self) -> dict[str, Any]:
        if not self.summary_cache_path.exists():
            return {}
        try:
            payload = json.loads(self.summary_cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return dict(payload) if isinstance(payload, Mapping) else {}

    def _write_summary_cache(self, payload: Mapping[str, Any]) -> None:
        self.summary_cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.summary_cache_path.with_suffix(f"{self.summary_cache_path.suffix}.tmp")
        temp_path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(self.summary_cache_path)


def _default_llm_client_factory(route: str) -> Any:
    return build_openai_compatible_client_from_config(route_id=route)


def summary_cache_key(paper: PublicPaper, *, locale: PaperLocale, route: str) -> str:
    return ":".join((paper.id, paper_abstract_hash(paper), locale, route))


def paper_abstract_hash(paper: PublicPaper) -> str:
    return hashlib.sha256(paper.abstractSnippet.encode("utf-8")).hexdigest()[:16]


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
                metric=_optional_text(value.get("metric")),
                value=value.get("value") if isinstance(value.get("value"), (str, int, float)) else value.get("bestValue"),
                taskSlug=_optional_text(value.get("taskSlug")),
                url=_normalized_https_url(value.get("url")),
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
        " ".join(ref.name for ref in paper.methodRefs),
        " ".join(ref.slug for ref in paper.methodRefs),
    ]
    return " ".join(parts).casefold()


def _summary_request(paper: PublicPaper, *, locale: PaperLocale) -> LLMRequest:
    language = "Chinese" if locale == "zh" else "English"
    return LLMRequest(
        messages=[
            LLMMessage.system(
                "You write concise, evidence-oriented research summaries for NewsRoom. "
                "Use only the provided paper metadata. Return strict JSON with keys: "
                "summary, keyInsights, limitations."
            ),
            LLMMessage.user(
                f"Language: {language}\n"
                f"Title: {paper.title}\n"
                f"Authors: {', '.join(paper.authors)}\n"
                f"Venue: {paper.venue or 'Paper'}\n"
                f"Published: {paper.publishedAt}\n"
                f"Abstract: {paper.abstractSnippet}\n"
                "Write one paragraph summary, 3 keyInsights, and 1-2 limitations."
            ),
        ],
        temperature=0.2,
        max_tokens=700,
        response_format={"type": "json_object"},
        metadata={"paper_id": paper.id, "locale": locale},
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


def _summary_from_payload(payload: Mapping[str, Any]) -> PaperAISummary | None:
    paper_id = _text(payload.get("paperId"))
    locale = _text(payload.get("locale"))
    route = _text(payload.get("modelRoute"))
    abstract_hash = _text(payload.get("abstractHash"))
    summary = _text(payload.get("summary"))
    if not paper_id or locale not in {"zh", "en"} or not route or not abstract_hash or not summary:
        return None
    return PaperAISummary(
        paperId=paper_id,
        locale=locale,  # type: ignore[arg-type]
        modelRoute=route,
        abstractHash=abstract_hash,
        summary=summary,
        keyInsights=tuple(_string_list(payload.get("keyInsights"))),
        limitations=tuple(_string_list(payload.get("limitations"))),
        generatedAt=_text(payload.get("generatedAt")),
        cached=True,
    )


def _papers_data_path(configured_path: str | Path | None) -> Path:
    if configured_path is not None:
        return Path(configured_path).expanduser().resolve()
    env_path = os.environ.get(PAPERS_DATA_PATH_ENV)
    if env_path:
        return Path(env_path).expanduser().resolve()
    return _project_root() / "frontend" / "data" / "papers" / "arxiv-papers.json"


def _summary_cache_path(configured_path: str | Path | None) -> Path:
    if configured_path is not None:
        return Path(configured_path).expanduser().resolve()
    env_path = os.environ.get(PAPERS_SUMMARY_CACHE_PATH_ENV)
    if env_path:
        return Path(env_path).expanduser().resolve()
    return _project_root() / ".newsroom" / "papers" / "ai-summaries.json"


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
            refs.append(PaperRef(id=ref_id, slug=slug, name=name, nameZh=_optional_text(item.get("nameZh"))))
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
