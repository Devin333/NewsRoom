from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from business.boards.paper_radar.public_mapper import sanitize_public_payload


PRIVATE_FIELD_NAMES = {"raw_payload", "raw_content", "raw_html", "full_text", "secret", "api_key", "token", "authorization"}

SECTION_TYPE_KEYWORDS = {
    "method": {"method", "methods", "architecture", "approach", "model", "algorithm", "task", "tasks"},
    "experiment": {"experiment", "experiments", "evaluation", "evaluate", "evaluated", "task", "tasks"},
    "limitation": {"limitation", "limitations", "weakness", "weaknesses", "failure", "caveat", "risk", "risks"},
    "implementation": {"implementation", "implementations", "code", "repo", "repository", "github", "project"},
    "benchmark": {"benchmark", "benchmarks", "metric", "score", "result", "results", "performance"},
    "evidence": {"evidence", "source", "sources", "citation", "citations", "reference", "references"},
    "contribution": {"contribution", "contributions", "insight", "insights", "novel", "main"},
    "summary": {"summary", "overview", "tldr", "explain"},
    "abstract": {"abstract"},
}


@dataclass(frozen=True)
class PaperReaderQuestion:
    paperId: str
    locale: str
    question: str


@dataclass(frozen=True)
class PaperReaderCitation:
    id: str
    label: str
    sourceType: str
    sectionId: str | None = None
    evidenceId: str | None = None
    sourceId: str | None = None
    textExcerpt: str | None = None
    url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "label": self.label,
            "sourceType": self.sourceType,
        }
        for key, value in (
            ("sectionId", self.sectionId),
            ("evidenceId", self.evidenceId),
            ("sourceId", self.sourceId),
            ("textExcerpt", self.textExcerpt),
            ("url", self.url),
        ):
            if value:
                payload[key] = value
        return payload


@dataclass(frozen=True)
class PaperReaderAnswer:
    paperId: str
    locale: str
    question: str
    answer: str
    citations: tuple[PaperReaderCitation, ...]
    confidence: float
    generatedAt: str
    cached: bool = False

    def to_dict(self) -> dict[str, Any]:
        return sanitize_public_payload(
            {
                "paperId": self.paperId,
                "locale": self.locale,
                "question": self.question,
                "answer": self.answer,
                "citations": [citation.to_dict() for citation in self.citations],
                "confidence": self.confidence,
                "generatedAt": self.generatedAt,
                "cached": self.cached,
            }
        )


def answer_reader_question(
    reader_payload: Any,
    *,
    question: str,
    locale: str,
    generated_at: datetime | None = None,
) -> PaperReaderAnswer:
    paper = reader_payload.paper
    normalized_question = _normalize_question(question)
    sections = tuple(getattr(reader_payload, "sections", ()))
    ranked_sections = _rank_sections(sections, normalized_question)
    selected_sections = ranked_sections[:3] if ranked_sections else list(sections[:1])
    citations = _citations_for_sections(selected_sections)
    evidence_citations = _evidence_citations(getattr(paper, "evidenceRefs", ()))
    if evidence_citations:
        citations = tuple(list(citations) + list(evidence_citations[:2]))

    answer = _compose_answer(
        paper_title=getattr(paper, "title", "this paper"),
        question=normalized_question,
        sections=selected_sections,
        locale=locale,
    )
    confidence = _confidence(selected_sections, normalized_question)
    return PaperReaderAnswer(
        paperId=paper.id,
        locale=locale,
        question=question.strip(),
        answer=answer,
        citations=citations,
        confidence=confidence,
        generatedAt=(generated_at or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z"),
        cached=False,
    )


def answer_cache_key(reader_payload: Any, *, question: str, locale: str) -> str:
    paper = reader_payload.paper
    sections = getattr(reader_payload, "sections", ())
    section_hash = hashlib.sha256(
        "\n".join(f"{getattr(section, 'id', '')}:{getattr(section, 'textExcerpt', '')}" for section in sections).encode("utf-8")
    ).hexdigest()[:16]
    question_hash = hashlib.sha256(_normalize_question(question).encode("utf-8")).hexdigest()[:16]
    return ":".join((paper.id, locale, section_hash, question_hash))


def copy_answer(answer: PaperReaderAnswer, *, cached: bool) -> PaperReaderAnswer:
    return PaperReaderAnswer(**(answer.__dict__ | {"cached": cached}))


def answer_from_payload(payload: Mapping[str, Any]) -> PaperReaderAnswer | None:
    paper_id = _text(payload.get("paperId"))
    locale = _text(payload.get("locale"))
    question = _text(payload.get("question"))
    answer = _text(payload.get("answer"))
    generated_at = _text(payload.get("generatedAt"))
    if not paper_id or locale not in {"zh", "en"} or not question or not answer or not generated_at:
        return None
    citations = tuple(_citation_from_payload(item) for item in _sequence(payload.get("citations")))
    return PaperReaderAnswer(
        paperId=paper_id,
        locale=locale,
        question=question,
        answer=answer,
        citations=tuple(citation for citation in citations if citation is not None),
        confidence=_float(payload.get("confidence"), default=0.0),
        generatedAt=generated_at,
        cached=bool(payload.get("cached")),
    )


def _citation_from_payload(payload: Any) -> PaperReaderCitation | None:
    if not isinstance(payload, Mapping):
        return None
    citation_id = _text(payload.get("id"))
    label = _text(payload.get("label"))
    source_type = _text(payload.get("sourceType"))
    if not citation_id or not label or not source_type:
        return None
    return PaperReaderCitation(
        id=citation_id,
        label=label,
        sourceType=source_type,
        sectionId=_optional_text(payload.get("sectionId")),
        evidenceId=_optional_text(payload.get("evidenceId")),
        sourceId=_optional_text(payload.get("sourceId")),
        textExcerpt=_optional_text(payload.get("textExcerpt")),
        url=_optional_text(payload.get("url")),
    )


def _rank_sections(sections: Sequence[Any], question: str) -> list[Any]:
    terms = _terms(question)
    scored: list[tuple[float, Any]] = []
    for section in sections:
        section_type = _text(getattr(section, "sectionType", "")).casefold()
        text = (
            f"{section_type} {getattr(section, 'title', '')} "
            f"{getattr(section, 'summary', '') or ''} {getattr(section, 'textExcerpt', '')}"
        )
        score = sum(1 for term in terms if term in text.casefold())
        if section_type in SECTION_TYPE_KEYWORDS and terms.intersection(SECTION_TYPE_KEYWORDS[section_type]):
            score += 3
        if not terms and text.strip():
            score = 1
        if score:
            scored.append((float(score), section))
    return [section for _, section in sorted(scored, key=lambda item: item[0], reverse=True)]


def _compose_answer(*, paper_title: str, question: str, sections: Sequence[Any], locale: str) -> str:
    excerpts = [_trim_excerpt(getattr(section, "summary", None) or getattr(section, "textExcerpt", "")) for section in sections]
    excerpts = [excerpt for excerpt in excerpts if excerpt]
    if not excerpts:
        return (
            "I could not find enough public section evidence in this reader payload to answer that question."
            if locale == "en"
            else "当前 reader payload 中没有足够的公开 section 证据回答这个问题。"
        )
    if locale == "zh":
        return f"基于《{paper_title}》当前可用的公开 section，答案是：{excerpts[0]}" + (
            f" 另一个相关证据是：{excerpts[1]}" if len(excerpts) > 1 else ""
        )
    return f"Based on the available public sections for {paper_title}, the answer is: {excerpts[0]}" + (
        f" A second relevant signal is: {excerpts[1]}" if len(excerpts) > 1 else ""
    )


def _citations_for_sections(sections: Sequence[Any]) -> tuple[PaperReaderCitation, ...]:
    citations: list[PaperReaderCitation] = []
    for index, section in enumerate(sections, start=1):
        section_id = _text(getattr(section, "id", ""))
        if not section_id:
            continue
        citations.append(
            PaperReaderCitation(
                id=f"section-{index}",
                label=_text(getattr(section, "title", "")) or f"Section {index}",
                sourceType="section",
                sectionId=section_id,
                textExcerpt=_trim_excerpt(_text(getattr(section, "textExcerpt", "")), limit=220),
            )
        )
    return tuple(citations)


def _evidence_citations(evidence_refs: Sequence[Any]) -> tuple[PaperReaderCitation, ...]:
    citations: list[PaperReaderCitation] = []
    for index, raw in enumerate(evidence_refs, start=1):
        if not isinstance(raw, Mapping):
            continue
        ref = sanitize_public_payload(raw)
        if not isinstance(ref, Mapping) or _contains_private_key(ref):
            continue
        evidence_id = _text(ref.get("evidenceId")) or _text(ref.get("id")) or f"evidence-{index}"
        citations.append(
            PaperReaderCitation(
                id=f"evidence-{index}",
                label=_text(ref.get("title")) or _text(ref.get("sourceName")) or evidence_id,
                sourceType="evidence",
                evidenceId=evidence_id,
                sourceId=_optional_text(ref.get("sourceId")),
                textExcerpt=_optional_text(ref.get("summary") or ref.get("quote")),
                url=_optional_text(ref.get("url")),
            )
        )
    return tuple(citations)


def _contains_private_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(str(key).casefold() in PRIVATE_FIELD_NAMES or _contains_private_key(item) for key, item in value.items())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return any(_contains_private_key(item) for item in value)
    return False


def _confidence(sections: Sequence[Any], question: str) -> float:
    terms = _terms(question)
    if not sections:
        return 0.0
    if not terms:
        return 0.45
    text = " ".join(_text(getattr(section, "textExcerpt", "")) for section in sections).casefold()
    matched = sum(1 for term in terms if term in text)
    return round(min(0.9, 0.35 + matched / max(len(terms), 1) * 0.55), 2)


def _terms(value: str) -> set[str]:
    return {part for part in re.findall(r"[\w-]+", value.casefold()) if len(part) > 2}


def _normalize_question(question: str) -> str:
    return " ".join(question.strip().split())[:1000]


def _trim_excerpt(value: str, *, limit: int = 360) -> str:
    text = " ".join(value.split())
    return text if len(text) <= limit else f"{text[: limit - 1].rstrip()}..."


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _float(value: Any, *, default: float) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default
