from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query

from interfaces.api.deps import ApiRouteHelpers, ApiServices


DEFAULT_LIMIT = 1000
MAX_LIMIT = 5000
PAPERS_DATA_PATH_ENV = "NEWSROOM_PAPERS_DATA_PATH"
GITHUB_REPO_PATTERN = re.compile(r"https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


def create_router(services: ApiServices, helpers: ApiRouteHelpers) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/papers")
    def list_papers(
        limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
        offset: int = Query(0, ge=0),
        q: str | None = Query(None, max_length=200),
    ):
        cache_path = _papers_data_path()
        if not cache_path.exists():
            return helpers.error(
                status_code=404,
                code="papers_cache_not_found",
                message="papers data cache was not found",
                user_action_required=True,
            )

        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return helpers.error(
                status_code=500,
                code="papers_cache_invalid",
                message="papers data cache could not be read",
                details={"reason": str(exc)},
                retryable=True,
            )

        raw_papers = cache.get("papers") if isinstance(cache, Mapping) else None
        papers = [_paper_payload(raw_paper) for raw_paper in _sequence(raw_papers)]
        published_papers = [paper for paper in papers if paper is not None and paper.get("isPublished") is not False]
        filtered_papers = _filter_papers(published_papers, q)
        page = filtered_papers[offset : offset + limit]

        return helpers.success(
            {
                "source": _text(cache.get("source")) if isinstance(cache, Mapping) else "papers-cache",
                "query": q or "",
                "collectedAt": _text(cache.get("collectedAt")) if isinstance(cache, Mapping) else None,
                "paper_count": len(page),
                "total_count": len(filtered_papers),
                "source_count": len(published_papers),
                "limit": limit,
                "offset": offset,
                "papers": page,
            }
        )

    return router


def _papers_data_path() -> Path:
    configured_path = os.environ.get(PAPERS_DATA_PATH_ENV)
    if configured_path:
        return Path(configured_path).expanduser().resolve()

    project_root = Path(__file__).resolve().parents[3]
    return project_root / "frontend" / "data" / "papers" / "arxiv-papers.json"


def _paper_payload(raw_paper: Any) -> dict[str, Any] | None:
    if not isinstance(raw_paper, Mapping):
        return None

    paper_id = _text(raw_paper.get("id"))
    title = _text(raw_paper.get("title"))
    abstract = _text(raw_paper.get("abstractSnippet")) or _text(raw_paper.get("summary"))
    paper_url = _text(raw_paper.get("paperUrl")) or _text(raw_paper.get("url"))

    if not paper_id or not title or not abstract or not paper_url:
        return None

    payload: dict[str, Any] = {
        "id": paper_id,
        "slug": _text(raw_paper.get("slug")) or paper_id,
        "title": title,
        "abstractSnippet": abstract,
        "authors": _string_list(raw_paper.get("authors")),
        "publishedAt": _text(raw_paper.get("publishedAt")) or _text(raw_paper.get("published_at")),
        "venue": _text(raw_paper.get("venue")) or "arXiv",
        "citationDoi": _text(raw_paper.get("citationDoi")) or _text(raw_paper.get("doi")),
        "thumbnailUrl": _optional_text(raw_paper.get("thumbnailUrl")),
        "tags": _string_list(raw_paper.get("tags")),
        "taskRefs": _refs(raw_paper.get("taskRefs")),
        "methodRefs": _refs(raw_paper.get("methodRefs")),
        "paperUrl": paper_url,
        "arxivUrl": _optional_text(raw_paper.get("arxivUrl")),
        "pdfUrl": _optional_text(raw_paper.get("pdfUrl")),
        "repoUrl": _paper_repo_url(raw_paper, abstract),
        "isPublished": raw_paper.get("isPublished") is not False,
    }

    for source_key, target_key in (
        ("titleZh", "titleZh"),
        ("abstractSnippetZh", "abstractSnippetZh"),
    ):
        value = _optional_text(raw_paper.get(source_key))
        if value is not None:
            payload[target_key] = value

    for source_key, target_key in (
        ("citationCount", "citationCount"),
        ("githubMomentum", "githubMomentum"),
        ("githubStars", "githubStars"),
        ("starsPerHour", "starsPerHour"),
    ):
        value = _number(raw_paper.get(source_key))
        if value is not None:
            payload[target_key] = value

    return payload


def _filter_papers(papers: list[dict[str, Any]], query: str | None) -> list[dict[str, Any]]:
    normalized_query = (query or "").strip().lower()
    if not normalized_query:
        return papers

    return [paper for paper in papers if normalized_query in _paper_search_text(paper)]


def _paper_repo_url(raw_paper: Mapping[str, Any], abstract: str) -> str | None:
    explicit_repo = _optional_text(raw_paper.get("repoUrl"))
    if explicit_repo:
        return _normalize_github_repo_url(explicit_repo)

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
    match = GITHUB_REPO_PATTERN.search(value)
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
    if parsed.scheme != "https" or parsed.netloc.lower().removeprefix("www.") != "github.com":
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    owner = parts[0].strip().rstrip(".,;:)]}>'\"")
    repo = parts[1].strip().removesuffix(".git").rstrip(".,;:)]}>'\"")
    if not owner or not repo:
        return None
    return f"https://github.com/{owner}/{repo}"


def _paper_search_text(paper: Mapping[str, Any]) -> str:
    parts = [
        _text(paper.get("title")),
        _text(paper.get("abstractSnippet")),
        " ".join(_string_list(paper.get("authors"))),
        " ".join(_string_list(paper.get("tags"))),
    ]
    return " ".join(parts).lower()


def _refs(value: Any) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for item in _sequence(value):
        if not isinstance(item, Mapping):
            continue
        ref_id = _text(item.get("id"))
        slug = _text(item.get("slug"))
        name = _text(item.get("name"))
        if ref_id and slug and name:
            refs.append({"id": ref_id, "slug": slug, "name": name})
    return refs


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split() if item.strip()]
    return [_text(item) for item in _sequence(value) if _text(item)]


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, str | bytes) else []


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _number(value: Any) -> float | int | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
