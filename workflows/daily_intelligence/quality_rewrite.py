from __future__ import annotations

from typing import Any

from evidence import EvidenceBundle


def rewrite_report_draft(
    report_draft: dict[str, Any],
    evidence_bundle: EvidenceBundle,
    review: Any,
) -> dict[str, Any]:
    sections = [dict(section) for section in report_draft.get("sections", [])]
    sections = _drop_duplicate_sections(sections)
    unsupported_claims = _unsupported_claim_texts(review.unsupported_claims)
    if unsupported_claims:
        sections = [
            rewritten
            for section in sections
            if (rewritten := _remove_unsupported_claims(section, unsupported_claims)) is not None
        ]
    evidence_by_url = {item.source_url: item for item in evidence_bundle.items}
    for section in sections:
        sources = section.get("sources") or section.get("source_urls") or []
        if not sources:
            matched_urls = _matching_source_urls(str(section.get("content", "")), evidence_by_url)
            if matched_urls:
                section["sources"] = matched_urls
        section["claim_grounding"] = _filtered_claim_grounding(
            section,
            section.get("claim_grounding") or [],
        )
    rewritten = dict(report_draft)
    rewritten["sections"] = sections
    metadata = dict(rewritten.get("metadata") or {})
    metadata["rewrite"] = {
        "method": "rule",
        "instructions": list(review.rewrite_instructions),
        "preserve_evidence_boundary": True,
    }
    rewritten["metadata"] = metadata
    return rewritten


def _drop_duplicate_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    deduplicated = []
    for section in sections:
        key = " ".join(str(section.get("content", "")).split()).casefold()
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        deduplicated.append(section)
    return deduplicated


def _unsupported_claim_texts(unsupported_claims: list[str]) -> list[str]:
    texts = []
    for claim in unsupported_claims:
        if ": " in claim:
            texts.append(claim.split(": ", 1)[1])
        else:
            texts.append(claim)
    return texts


def _remove_unsupported_claims(
    section: dict[str, Any],
    unsupported_claims: list[str],
) -> dict[str, Any] | None:
    content = str(section.get("content", ""))
    for claim in unsupported_claims:
        content = content.replace(claim, "").strip()
    content = " ".join(content.split())
    if not content:
        return None
    updated = dict(section)
    updated["content"] = content
    return updated


def _matching_source_urls(content: str, evidence_by_url: dict[str, Any]) -> list[str]:
    matches = []
    for url, item in evidence_by_url.items():
        if _token_overlap(content, f"{item.title} {item.summary}") >= 0.25:
            matches.append(url)
    return sorted(matches)


def _filtered_claim_grounding(
    section: dict[str, Any],
    claim_grounding: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    content = str(section.get("content", "")).casefold()
    filtered = []
    for grounded_claim in claim_grounding:
        if not isinstance(grounded_claim, dict):
            continue
        text = str(grounded_claim.get("text") or grounded_claim.get("claim") or "").strip()
        if text and text.casefold() not in content:
            continue
        filtered.append(dict(grounded_claim))
    return filtered


def _token_overlap(left: str, right: str) -> float:
    import re

    left_tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", left.casefold())
        if len(token) > 2
    }
    if not left_tokens:
        return 0.0
    right_tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", right.casefold())
        if len(token) > 2
    }
    if not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens)
