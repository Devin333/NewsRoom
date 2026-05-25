from __future__ import annotations

import hashlib
from urllib.parse import urlparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from business.boards.paper_radar.public_mapper import sanitize_public_payload


PAPER_SOURCE_TYPES = {"arxiv", "paper", "paper_index", "openreview", "acl", "pmlr", "neurips", "cvf"}
PROJECT_SOURCE_TYPES = {"github", "repo", "repository", "code"}
NEWS_SOURCE_TYPES = {
    "ai_news",
    "official_blog",
    "rss",
    "blog",
    "press",
    "press_release",
    "community",
    "community_pulse",
    "news",
    "media",
    "web",
}
PAPER_HOSTS = {
    "arxiv.org",
    "openreview.net",
    "aclanthology.org",
    "proceedings.mlr.press",
    "papers.nips.cc",
    "proceedings.neurips.cc",
    "openaccess.thecvf.com",
}


@dataclass(frozen=True)
class PaperSection:
    id: str
    paperId: str
    title: str
    level: int
    pageStart: int | None
    pageEnd: int | None
    textExcerpt: str
    summary: str | None
    sectionType: str

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "paperId": self.paperId,
            "title": self.title,
            "level": self.level,
            "textExcerpt": self.textExcerpt,
            "sectionType": self.sectionType,
        }
        if self.pageStart is not None:
            payload["pageStart"] = self.pageStart
        if self.pageEnd is not None:
            payload["pageEnd"] = self.pageEnd
        if self.summary:
            payload["summary"] = self.summary
        return payload


@dataclass(frozen=True)
class PaperReaderQuality:
    paperId: str
    pdfAvailable: bool
    textExtracted: bool
    summaryAvailable: bool
    implementationVerified: bool
    benchmarkVerified: bool
    evidenceCoverage: float
    lastUpdatedAt: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "paperId": self.paperId,
            "pdfAvailable": self.pdfAvailable,
            "textExtracted": self.textExtracted,
            "summaryAvailable": self.summaryAvailable,
            "implementationVerified": self.implementationVerified,
            "benchmarkVerified": self.benchmarkVerified,
            "evidenceCoverage": self.evidenceCoverage,
            "lastUpdatedAt": self.lastUpdatedAt,
        }


@dataclass(frozen=True)
class PaperReaderPayload:
    paper: Any
    sections: tuple[PaperSection, ...]
    aiSummary: Any | None
    readerNotes: tuple[Mapping[str, Any], ...]
    relatedPapers: tuple[Mapping[str, Any], ...]
    relatedProjects: tuple[Mapping[str, Any], ...]
    relatedNews: tuple[Mapping[str, Any], ...]
    quality: PaperReaderQuality

    def to_dict(self) -> dict[str, Any]:
        return sanitize_public_payload(
            {
                "paper": self.paper.to_dict(),
                "sections": [section.to_dict() for section in self.sections],
                "aiSummary": self.aiSummary.to_dict() if self.aiSummary is not None else None,
                "readerNotes": list(self.readerNotes),
                "relatedPapers": list(self.relatedPapers),
                "relatedProjects": list(self.relatedProjects),
                "relatedNews": list(self.relatedNews),
                "quality": self.quality.to_dict(),
            }
        )


def build_reader_payload(
    paper: Any,
    *,
    ai_summary: Any | None,
    related_paper_candidates: Sequence[Any] = (),
) -> PaperReaderPayload:
    sections = tuple(_build_sections(paper, ai_summary=ai_summary))
    quality = PaperReaderQuality(
        paperId=paper.id,
        pdfAvailable=bool(paper.pdfUrl),
        textExtracted=False,
        summaryAvailable=ai_summary is not None,
        implementationVerified=bool(paper.implementations),
        benchmarkVerified=bool(paper.benchmarks),
        evidenceCoverage=1.0 if getattr(paper, "evidenceRefs", ()) else 0.0,
        lastUpdatedAt=paper.publishedAt,
    )
    return PaperReaderPayload(
        paper=paper,
        sections=sections,
        aiSummary=ai_summary,
        readerNotes=(),
        relatedPapers=tuple(_related_papers(paper, related_paper_candidates)),
        relatedProjects=tuple(_related_projects(paper)),
        relatedNews=tuple(_related_news(paper)),
        quality=quality,
    )


def _build_sections(paper: Any, *, ai_summary: Any | None) -> list[PaperSection]:
    sections: list[PaperSection] = []
    seen_text: set[str] = set()

    def append(section_id: str, title: str, text: str, section_type: str, *, summary: str | None = None) -> None:
        text_excerpt = _clean_text(text)
        if not text_excerpt:
            return
        dedupe_key = text_excerpt.casefold()
        if dedupe_key in seen_text:
            return
        seen_text.add(dedupe_key)
        sections.append(
            PaperSection(
                id=f"{paper.id}:{section_id}",
                paperId=paper.id,
                title=title,
                level=1,
                pageStart=None,
                pageEnd=None,
                textExcerpt=text_excerpt,
                summary=_clean_text(summary) or None,
                sectionType=section_type,
            )
        )

    append("abstract", "Abstract", getattr(paper, "abstractSnippet", ""), "abstract")

    if ai_summary is not None:
        append("summary", "AI Summary", getattr(ai_summary, "summary", ""), "summary")
        append(
            "contribution",
            "Key Contributions",
            _bullet_text(getattr(ai_summary, "keyInsights", ())),
            "contribution",
        )
        append(
            "limitation",
            "Limitations",
            _bullet_text(getattr(ai_summary, "limitations", ())),
            "limitation",
        )

    task_names = _ref_names(getattr(paper, "taskRefs", ()))
    method_names = _ref_names(getattr(paper, "methodRefs", ()))
    append(
        "method",
        "Method and Task Signals",
        _join_sentences(
            [
                _labelled_list("Tasks", task_names),
                _labelled_list("Methods", method_names),
            ]
        ),
        "method",
    )

    benchmarks = tuple(getattr(paper, "benchmarks", ()))
    append(
        "experiment",
        "Experiment Signals",
        _experiment_text(task_names, benchmarks),
        "experiment",
    )
    append("benchmark", "Benchmark Results", _benchmark_text(benchmarks), "benchmark")

    implementations = tuple(getattr(paper, "implementations", ()))
    append("implementation", "Implementations", _implementation_text(implementations), "implementation")

    evidence_refs = tuple(getattr(paper, "evidenceRefs", ()))
    source_refs = tuple(getattr(paper, "sourceRefs", ()))
    append("evidence", "Evidence and Sources", _refs_text(evidence_refs, source_refs), "evidence")

    return sections


def _ref_names(refs: Sequence[Any]) -> list[str]:
    names: list[str] = []
    for ref in refs:
        name = _clean_text(getattr(ref, "name", ""))
        if name:
            names.append(name)
    return _unique(names)


def _implementation_text(implementations: Sequence[Any]) -> str:
    lines: list[str] = []
    for item in implementations:
        parts = [
            _clean_text(getattr(item, "name", "")),
            _clean_text(getattr(item, "repoUrl", "")),
        ]
        stars = getattr(item, "githubStars", None)
        if isinstance(stars, int):
            parts.append(f"{stars} GitHub stars")
        line = " / ".join(part for part in parts if part)
        if line:
            lines.append(line)
    return _bullet_text(lines)


def _benchmark_text(benchmarks: Sequence[Any]) -> str:
    lines: list[str] = []
    for item in benchmarks:
        parts = [_clean_text(getattr(item, "name", ""))]
        metric = _clean_text(getattr(item, "metric", ""))
        value = getattr(item, "value", None)
        if metric:
            parts.append(metric)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            parts.append(str(value))
        task_slug = _clean_text(getattr(item, "taskSlug", ""))
        if task_slug:
            parts.append(f"task {task_slug}")
        url = _clean_text(getattr(item, "url", ""))
        if url:
            parts.append(url)
        line = " / ".join(part for part in parts if part)
        if line:
            lines.append(line)
    return _bullet_text(lines)


def _experiment_text(task_names: Sequence[str], benchmarks: Sequence[Any]) -> str:
    benchmark_names = [_clean_text(getattr(item, "name", "")) for item in benchmarks]
    return _join_sentences(
        [
            _labelled_list("Evaluation tasks", task_names),
            _labelled_list("Reported benchmark records", _unique([name for name in benchmark_names if name])),
        ]
    )


def _refs_text(evidence_refs: Sequence[Mapping[str, Any]], source_refs: Sequence[Mapping[str, Any]]) -> str:
    lines: list[str] = []
    for ref in [*evidence_refs, *source_refs]:
        sanitized = sanitize_public_payload(ref)
        if not isinstance(sanitized, Mapping):
            continue
        parts = [
            _clean_text(sanitized.get("title")),
            _clean_text(sanitized.get("sourceName")),
            _clean_text(sanitized.get("sourceType")),
            _clean_text(sanitized.get("summary")),
            _clean_text(sanitized.get("quote")),
            _clean_text(sanitized.get("url")),
        ]
        line = " / ".join(part for part in parts if part)
        if line:
            lines.append(line)
    return _bullet_text(_unique(lines))


def _related_papers(paper: Any, candidates: Sequence[Any]) -> list[Mapping[str, Any]]:
    related: list[tuple[float, str, Mapping[str, Any]]] = []
    for candidate in candidates:
        if getattr(candidate, "id", None) == getattr(paper, "id", None):
            continue
        score, reasons = _paper_relation_score(paper, candidate)
        if score <= 0:
            continue
        title = _clean_text(getattr(candidate, "title", ""))
        slug = _clean_text(getattr(candidate, "slug", ""))
        candidate_id = _clean_text(getattr(candidate, "id", ""))
        if not title or not slug or not candidate_id:
            continue
        item: dict[str, Any] = {
            "id": candidate_id,
            "title": title,
            "slug": slug,
            "relationReason": "; ".join(reasons[:3]),
            "score": round(score, 2),
        }
        for key, value in (
            ("venue", _clean_text(getattr(candidate, "venue", ""))),
            ("publishedAt", _clean_text(getattr(candidate, "publishedAt", ""))),
            ("paperUrl", _clean_text(getattr(candidate, "paperUrl", ""))),
        ):
            if value:
                item[key] = value
        related.append((score, title.casefold(), item))
    return [item for _, _, item in sorted(related, key=lambda entry: (-entry[0], entry[1]))[:5]]


def _paper_relation_score(paper: Any, candidate: Any) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    shared_methods = _shared_ref_names(getattr(paper, "methodRefs", ()), getattr(candidate, "methodRefs", ()))
    if shared_methods:
        score += len(shared_methods) * 4
        reasons.append(f"Shared methods: {', '.join(shared_methods[:2])}")
    shared_tasks = _shared_ref_names(getattr(paper, "taskRefs", ()), getattr(candidate, "taskRefs", ()))
    if shared_tasks:
        score += len(shared_tasks) * 3
        reasons.append(f"Shared tasks: {', '.join(shared_tasks[:2])}")
    shared_tags = _shared_text(getattr(paper, "tags", ()), getattr(candidate, "tags", ()))
    if shared_tags:
        score += min(len(shared_tags), 3)
        reasons.append(f"Shared tags: {', '.join(shared_tags[:3])}")
    if _clean_text(getattr(paper, "venue", "")).casefold() == _clean_text(getattr(candidate, "venue", "")).casefold():
        if _clean_text(getattr(paper, "venue", "")):
            score += 1
            reasons.append(f"Same venue: {_clean_text(getattr(paper, 'venue', ''))}")
    source_overlap = _shared_text(_ref_keys(getattr(paper, "sourceRefs", ())), _ref_keys(getattr(candidate, "sourceRefs", ())))
    evidence_overlap = _shared_text(_ref_keys(getattr(paper, "evidenceRefs", ())), _ref_keys(getattr(candidate, "evidenceRefs", ())))
    if source_overlap or evidence_overlap:
        score += 1.5
        reasons.append("Shared source/evidence")
    return score, reasons


def _related_projects(paper: Any) -> list[Mapping[str, Any]]:
    projects: list[Mapping[str, Any]] = []
    seen_urls: set[str] = set()

    def append(name: str, url: str, source_type: str, reason: str, score: float, *, github_stars: int | None = None) -> None:
        normalized_url = _clean_text(url)
        if not normalized_url or normalized_url in seen_urls:
            return
        seen_urls.add(normalized_url)
        item: dict[str, Any] = {
            "id": _stable_id(source_type, normalized_url),
            "name": _clean_text(name) or _project_name(normalized_url),
            "url": normalized_url,
            "sourceType": source_type,
            "relationReason": reason,
            "score": score,
        }
        if github_stars is not None:
            item["githubStars"] = github_stars
        projects.append(item)

    for implementation in getattr(paper, "implementations", ()):
        stars = getattr(implementation, "githubStars", None)
        append(
            getattr(implementation, "name", ""),
            getattr(implementation, "repoUrl", ""),
            "implementation",
            "Verified implementation repository",
            90,
            github_stars=stars if isinstance(stars, int) else None,
        )
    append(
        _project_name(_clean_text(getattr(paper, "repoUrl", ""))),
        getattr(paper, "repoUrl", ""),
        "repository",
        "Primary paper repository",
        80,
        github_stars=getattr(paper, "githubStars", None) if isinstance(getattr(paper, "githubStars", None), int) else None,
    )
    append(
        _project_name(_clean_text(getattr(paper, "projectUrl", ""))),
        getattr(paper, "projectUrl", ""),
        "project",
        "Project page linked by the paper",
        70,
    )
    return projects[:5]


def _related_news(paper: Any) -> list[Mapping[str, Any]]:
    refs: list[tuple[str, Mapping[str, Any]]] = []
    refs.extend(("evidence", ref) for ref in getattr(paper, "evidenceRefs", ()))
    refs.extend(("source", ref) for ref in getattr(paper, "sourceRefs", ()))
    news: list[Mapping[str, Any]] = []
    seen_urls: set[str] = set()
    for ref_kind, raw_ref in refs:
        sanitized = sanitize_public_payload(raw_ref)
        if not isinstance(sanitized, Mapping):
            continue
        url = _clean_text(sanitized.get("url") or sanitized.get("sourceUrl") or sanitized.get("source_url"))
        if not url or url in seen_urls or not _is_news_like_ref(sanitized, url):
            continue
        seen_urls.add(url)
        title = _clean_text(sanitized.get("title")) or _clean_text(sanitized.get("sourceName")) or _project_name(url)
        source_type = _clean_text(sanitized.get("sourceType") or sanitized.get("source_type")) or "source"
        item: dict[str, Any] = {
            "id": _stable_id("news", url),
            "title": title,
            "url": url,
            "sourceType": source_type,
            "relationReason": "Evidence source" if ref_kind == "evidence" else "Source reference",
            "score": 70 if ref_kind == "evidence" else 60,
        }
        summary = _clean_text(sanitized.get("summary") or sanitized.get("quote"))
        if summary:
            item["summary"] = summary
        news.append(item)
    return news[:5]


def _shared_ref_names(left: Sequence[Any], right: Sequence[Any]) -> list[str]:
    left_by_key = {_ref_key(ref): _clean_text(getattr(ref, "name", "")) for ref in left if _ref_key(ref)}
    right_keys = {_ref_key(ref) for ref in right if _ref_key(ref)}
    return _unique([name for key, name in left_by_key.items() if key in right_keys and name])


def _ref_key(ref: Any) -> str:
    return (_clean_text(getattr(ref, "slug", "")) or _clean_text(getattr(ref, "id", "")) or _clean_text(getattr(ref, "name", ""))).casefold()


def _ref_keys(refs: Sequence[Mapping[str, Any]]) -> list[str]:
    keys: list[str] = []
    for raw_ref in refs:
        ref = sanitize_public_payload(raw_ref)
        if not isinstance(ref, Mapping):
            continue
        for value in (
            ref.get("sourceId"),
            ref.get("sourceName"),
            ref.get("externalId"),
            ref.get("title"),
            ref.get("url"),
        ):
            text = _clean_text(value)
            if text:
                keys.append(text.casefold())
    return _unique(keys)


def _shared_text(left: Sequence[str], right: Sequence[str]) -> list[str]:
    right_keys = {value.casefold() for value in right}
    return _unique([value for value in left if value.casefold() in right_keys])


def _is_news_like_ref(ref: Mapping[str, Any], url: str) -> bool:
    source_type = _clean_text(ref.get("sourceType") or ref.get("source_type")).casefold()
    if source_type in PAPER_SOURCE_TYPES or source_type in PROJECT_SOURCE_TYPES:
        return False
    host = _url_host(url)
    if host in PAPER_HOSTS or host == "github.com":
        return False
    return source_type in NEWS_SOURCE_TYPES or bool(source_type and host)


def _url_host(url: str) -> str:
    try:
        return urlparse(url).netloc.casefold().removeprefix("www.")
    except ValueError:
        return ""


def _project_name(url: str) -> str:
    try:
        parsed = urlparse(url)
    except ValueError:
        return url
    path = "/".join(part for part in parsed.path.split("/") if part)
    return path or parsed.netloc or url


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}-{hashlib.sha1(value.encode('utf-8')).hexdigest()[:12]}"


def _bullet_text(values: Sequence[Any]) -> str:
    items = [_clean_text(value) for value in values]
    return "\n".join(f"- {item}" for item in _unique([item for item in items if item]))


def _labelled_list(label: str, values: Sequence[str]) -> str:
    cleaned = _unique([_clean_text(value) for value in values if _clean_text(value)])
    return f"{label}: {', '.join(cleaned)}." if cleaned else ""


def _join_sentences(values: Sequence[str]) -> str:
    return " ".join(value for value in (_clean_text(item) for item in values) if value)


def _unique(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _clean_text(value: Any) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""
