from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlparse


FORBIDDEN_PUBLIC_FIELD_NAMES = {
    "raw_payload",
    "raw_content",
    "raw_html",
    "full_text",
    "secret",
    "api_key",
    "token",
    "authorization",
}

PAPER_SOURCE_TYPES = {
    "arxiv",
    "paper",
    "paper_index",
    "openreview",
    "acl",
    "pmlr",
    "neurips",
    "cvf",
}

BLOCKED_SOURCE_TYPES = {
    "official_blog",
    "ai_news",
    "rss",
    "blog",
    "press_release",
    "community",
    "community_pulse",
    "project_radar",
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


def map_paper_radar_artifact_to_public_papers(payload: Mapping[str, Any]) -> dict[str, Any]:
    candidates = _candidate_records(payload)
    papers = []
    seen: set[str] = set()

    for index, record in enumerate(candidates):
        paper = _record_to_paper(record, index)
        if not paper:
            continue
        key = str(paper.get("id") or paper.get("paperUrl") or paper.get("title"))
        if key in seen:
            continue
        seen.add(key)
        papers.append(paper)

    return {
        "source": "paper_radar",
        "collectedAt": _text(payload.get("generated_at") or payload.get("completed_at") or payload.get("collectedAt")),
        "papers": papers,
    }


def sanitize_public_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.casefold() in FORBIDDEN_PUBLIC_FIELD_NAMES:
                continue
            cleaned[key_text] = sanitize_public_payload(item)
        return cleaned
    if isinstance(value, list):
        return [sanitize_public_payload(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_public_payload(item) for item in value]
    return value


def _candidate_records(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    records: list[Mapping[str, Any]] = []
    for value in (
        payload.get("papers"),
        payload.get("cards"),
        payload.get("items"),
        payload.get("normalized_items"),
        payload.get("raw_items"),
        _field(payload.get("board_output"), "cards"),
        _field(payload.get("board_output"), "items"),
        _field(payload.get("output"), "papers"),
        _field(payload.get("output"), "cards"),
        _field(payload.get("output"), "board_output", "cards"),
    ):
        records.extend(_records(value))

    ranked_items = _records(payload.get("ranked_items")) + _records(payload.get("ranked_signals"))
    for ranked in ranked_items:
        item = ranked.get("item")
        if isinstance(item, Mapping):
            records.append(item)
        else:
            records.append(ranked)

    return records


def _record_to_paper(record: Mapping[str, Any], index: int) -> dict[str, Any] | None:
    sanitized = sanitize_public_payload(record)
    if not isinstance(sanitized, Mapping) or not _is_true_paper_record(sanitized):
        return None

    title = _text(sanitized.get("title") or sanitized.get("headline"))
    abstract = _text(
        sanitized.get("abstractSnippet")
        or sanitized.get("abstract")
        or sanitized.get("summary")
        or sanitized.get("content_excerpt")
        or sanitized.get("description")
    )
    urls = _candidate_urls(sanitized)
    paper_url = _first(urls)
    if not title or not abstract or not paper_url:
        return None

    source_refs = _source_refs(sanitized)
    evidence_refs = _evidence_refs(sanitized)
    metadata = sanitized.get("metadata") if isinstance(sanitized.get("metadata"), Mapping) else {}
    source_type = _source_type(sanitized)

    paper = {
        "id": _text(sanitized.get("id") or sanitized.get("paper_id") or sanitized.get("signal_id") or sanitized.get("card_id"))
        or f"paper-radar-{index + 1}",
        "slug": _slugify(title),
        "title": title,
        "abstractSnippet": abstract,
        "authors": _string_list(sanitized.get("authors")),
        "publishedAt": _text(sanitized.get("publishedAt") or sanitized.get("published_at") or sanitized.get("generated_at")),
        "venue": _venue(sanitized),
        "tags": _tags(sanitized, source_type),
        "taskRefs": _refs(sanitized.get("taskRefs") or metadata.get("taskRefs") if isinstance(metadata, Mapping) else None),
        "methodRefs": _refs(sanitized.get("methodRefs") or metadata.get("methodRefs") if isinstance(metadata, Mapping) else None),
        "paperUrl": paper_url,
        "arxivUrl": _arxiv_url(urls),
        "pdfUrl": _pdf_url(sanitized, urls),
        "repoUrl": _repo_url(sanitized, urls),
        "projectUrl": _https_url(sanitized.get("projectUrl") or sanitized.get("project_url")),
        "citationCount": _number(sanitized.get("citationCount") or sanitized.get("citation_count")),
        "githubStars": _number(sanitized.get("githubStars") or sanitized.get("github_stars")),
        "newsroomHeatScore": _number(_score_value(sanitized)),
        "evidenceRefs": evidence_refs,
        "sourceRefs": source_refs,
        "isPublished": sanitized.get("isPublished") is not False,
    }
    return {key: value for key, value in paper.items() if value not in (None, "", [], {})}


def _is_true_paper_record(record: Mapping[str, Any]) -> bool:
    source_type = _source_type(record).casefold()
    signal_type = _text(record.get("signal_type")).casefold()
    evidence_type = _text(record.get("evidence_type")).casefold()
    metadata = record.get("metadata") if isinstance(record.get("metadata"), Mapping) else {}
    metadata_kind = _text(metadata.get("signal_kind") or metadata.get("source_kind")).casefold()
    urls = _candidate_urls(record)

    if source_type in BLOCKED_SOURCE_TYPES or signal_type in BLOCKED_SOURCE_TYPES:
        return False
    if source_type in PAPER_SOURCE_TYPES or signal_type == "paper" or evidence_type == "paper" or metadata_kind in {"paper", "arxiv"}:
        return True
    return any(_is_paper_url(url) for url in urls)


def _candidate_urls(record: Mapping[str, Any]) -> list[str]:
    source = record.get("source") if isinstance(record.get("source"), Mapping) else {}
    provenance = record.get("provenance") if isinstance(record.get("provenance"), Mapping) else {}
    refs = _records(record.get("sourceRefs")) + _records(record.get("source_refs"))
    refs += _records(record.get("evidenceRefs")) + _records(record.get("evidence_refs"))
    refs += _records(provenance.get("source_refs")) + _records(provenance.get("evidence_refs"))
    values = [
        record.get("paperUrl"),
        record.get("paper_url"),
        record.get("arxivUrl"),
        record.get("arxiv_url"),
        record.get("url"),
        record.get("source_url"),
        source.get("url"),
        source.get("source_url"),
    ]
    for ref in refs:
        values.extend([ref.get("url"), ref.get("source_url")])
    return _unique([url for url in (_https_url(value) for value in values) if url])


def _source_refs(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    source = record.get("source") if isinstance(record.get("source"), Mapping) else {}
    refs = _records(record.get("sourceRefs")) + _records(record.get("source_refs"))
    provenance = record.get("provenance") if isinstance(record.get("provenance"), Mapping) else {}
    refs += _records(provenance.get("source_refs"))
    if not refs and source:
        refs = [source]
    return [_compact_ref(ref) for ref in refs if _compact_ref(ref)]


def _evidence_refs(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    provenance = record.get("provenance") if isinstance(record.get("provenance"), Mapping) else {}
    refs = _records(record.get("evidenceRefs")) + _records(record.get("evidence_refs"))
    refs += _records(provenance.get("evidence_refs"))
    return [_compact_ref(ref) for ref in refs if _compact_ref(ref)]


def _compact_ref(ref: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        "sourceId": _text(ref.get("sourceId") or ref.get("source_id")),
        "sourceName": _text(ref.get("sourceName") or ref.get("source_name")),
        "sourceType": _text(ref.get("sourceType") or ref.get("source_type")),
        "url": _https_url(ref.get("url") or ref.get("source_url")),
        "externalId": _text(ref.get("externalId") or ref.get("external_id")),
        "title": _text(ref.get("title") or ref.get("label")),
    }
    return {key: value for key, value in result.items() if value}


def _source_type(record: Mapping[str, Any]) -> str:
    source = record.get("source") if isinstance(record.get("source"), Mapping) else {}
    metadata = record.get("metadata") if isinstance(record.get("metadata"), Mapping) else {}
    return _text(record.get("source_type") or source.get("source_type") or metadata.get("source_type"))


def _venue(record: Mapping[str, Any]) -> str:
    source = record.get("source") if isinstance(record.get("source"), Mapping) else {}
    return _text(record.get("venue") or record.get("source_name") or source.get("source_name") or _source_type(record)) or "PaperRadar"


def _tags(record: Mapping[str, Any], source_type: str) -> list[str]:
    return _unique([source_type, *_string_list(record.get("tags")), *_string_list(record.get("categories"))])[:6]


def _refs(value: Any) -> list[dict[str, str]]:
    refs = []
    for item in _records(value):
        ref_id = _text(item.get("id")) or _text(item.get("slug"))
        slug = _text(item.get("slug")) or _slugify(_text(item.get("name")))
        name = _text(item.get("name")) or slug
        if ref_id and slug and name:
            refs.append({"id": ref_id, "slug": slug, "name": name})
    return refs


def _arxiv_url(urls: Sequence[str]) -> str | None:
    return next((url for url in urls if "arxiv.org/abs/" in url), None)


def _pdf_url(record: Mapping[str, Any], urls: Sequence[str]) -> str | None:
    explicit = _https_url(record.get("pdfUrl") or record.get("pdf_url"))
    if explicit:
        return explicit
    for url in urls:
        parsed = urlparse(url)
        host = parsed.netloc.lower().removeprefix("www.")
        if host == "arxiv.org" and parsed.path.startswith("/abs/"):
            paper_id = parsed.path.removeprefix("/abs/").rstrip("/")
            return f"https://arxiv.org/pdf/{paper_id}.pdf" if paper_id else None
        if parsed.path.lower().endswith(".pdf"):
            return url
    return None


def _repo_url(record: Mapping[str, Any], urls: Sequence[str]) -> str | None:
    candidates = [
        _text(record.get("repoUrl")),
        _text(record.get("repo_url")),
        _text(record.get("githubUrl")),
        _text(record.get("github_url")),
        _text(record.get("codeUrl")),
        _text(record.get("code_url")),
        *urls,
    ]
    for value in candidates:
        match = re.search(r"https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value)
        if match:
            return _https_url(match.group(0).rstrip(".,;:)]}>'\""))
    return None


def _score_value(record: Mapping[str, Any]) -> Any:
    score = record.get("score")
    if isinstance(score, Mapping):
        return score.get("value")
    return record.get("newsroomHeatScore") or record.get("final_score") or record.get("score")


def _field(value: Any, *path: str) -> Any:
    current = value
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _records(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_text(item) for item in value if _text(item)]
    return []


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, (int, float)) else None


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _https_url(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = urlparse(text.replace("http://", "https://", 1))
    except ValueError:
        return None
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    return parsed.geturl()


def _is_paper_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    host = parsed.netloc.lower().removeprefix("www.")
    return host in PAPER_HOSTS


def _first(values: Sequence[str]) -> str | None:
    return values[0] if values else None


def _unique(values: Sequence[str]) -> list[str]:
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:80] or "paper"
