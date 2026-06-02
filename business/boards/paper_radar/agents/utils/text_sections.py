"""Text section helpers for paper structure analysis."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


SECTION_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("abstract", ("abstract",)),
    ("introduction", ("introduction", "background")),
    ("method", ("method", "approach", "model", "architecture")),
    ("experiment", ("experiment", "evaluation", "benchmark", "dataset")),
    ("result", ("result", "analysis", "table")),
    ("limitation", ("limitation", "failure", "threat")),
    ("conclusion", ("conclusion", "future work")),
    ("reference", ("reference", "bibliography")),
)


def build_semantic_sections(
    *,
    abstract: str,
    full_text: str | None,
    page_sections: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Build semantic sections from page-level sections or raw text excerpts."""

    sections: list[Mapping[str, Any]] = []
    if abstract:
        sections.append(_section("abstract-1", "Abstract", "abstract", abstract, None, None, 0.9))
    for index, section in enumerate(page_sections, start=1):
        text = str(section.get("textExcerpt") or section.get("text") or section.get("content") or "")
        title = str(section.get("title") or section.get("sectionType") or f"Section {index}")
        section_type = _section_type(f"{title} {text}")
        sections.append(
            _section(
                f"{section_type}-{index}",
                title,
                section_type,
                text,
                _optional_int(section.get("pageStart") or section.get("page")),
                _optional_int(section.get("pageEnd") or section.get("page")),
                0.82,
            )
        )
    if not page_sections and full_text:
        for index, chunk in enumerate(_split_full_text(full_text), start=1):
            section_type = _section_type(chunk)
            sections.append(
                _derived_section(
                    f"{section_type}-{index}",
                    _title(section_type),
                    section_type,
                    chunk,
                    None,
                    None,
                    0.68,
                )
            )
    return sections[:32]


def _section(section_id: str, title: str, section_type: str, text: str, page_start: int | None, page_end: int | None, confidence: float) -> Mapping[str, Any]:
    return {
        "sectionId": section_id,
        "title": title,
        "sectionType": section_type,
        "summary": " ".join(text.split())[:240],
        "textExcerpt": " ".join(text.split())[:1200],
        "pageStart": page_start,
        "pageEnd": page_end,
        "confidence": confidence,
    }


def _derived_section(
    section_id: str,
    title: str,
    section_type: str,
    text: str,
    page_start: int | None,
    page_end: int | None,
    confidence: float,
) -> Mapping[str, Any]:
    normalized = " ".join(text.split())
    return {
        "sectionId": section_id,
        "title": title,
        "sectionType": section_type,
        "summary": f"Derived {section_type} section from full text ({len(normalized)} characters).",
        "textExcerpt": f"Full-text derived {section_type} section; raw text is retained outside shared session.",
        "pageStart": page_start,
        "pageEnd": page_end,
        "confidence": confidence,
    }


def _section_type(text: str) -> str:
    lowered = text.casefold()
    for section_type, terms in SECTION_KEYWORDS:
        if any(term in lowered for term in terms):
            return section_type
    return "introduction"


def _split_full_text(full_text: str) -> list[str]:
    chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n|(?=^\d+\.?\s+[A-Z])", full_text, flags=re.MULTILINE) if chunk.strip()]
    return chunks[:12] or [full_text[:3000]]


def _title(section_type: str) -> str:
    return section_type.replace("-", " ").title()


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
