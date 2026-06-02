from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from business.foundation.value_normalization import (
    field_value as _field_value,
    list_value as _list_value,
    string_list as _string_list,
)


class ReportDraftNormalizationError(ValueError):
    pass


def normalize_report_draft(payload: Any) -> dict[str, Any]:
    if isinstance(payload, Mapping) and "report_draft" in payload and "sections" not in payload:
        payload = payload["report_draft"]
    if not isinstance(payload, Mapping):
        raise ReportDraftNormalizationError("report draft must be an object")
    draft = dict(payload)
    sections = draft.get("sections")
    if not isinstance(sections, list):
        raise ReportDraftNormalizationError("report draft sections must be a list")
    normalized_sections = []
    for index, section in enumerate(sections):
        if not isinstance(section, Mapping):
            raise ReportDraftNormalizationError(f"report draft section {index} must be an object")
        section_payload = dict(section)
        section_payload["title"] = str(section_payload.get("title") or f"Section {index + 1}")
        section_payload["content"] = str(section_payload.get("content") or "")
        section_payload["sources"] = _string_list(
            section_payload.get("sources") or section_payload.get("source_urls") or []
        )
        section_payload["section_id"] = str(
            section_payload.get("section_id")
            or section_payload.get("id")
            or f"section_{index + 1}"
        )
        section_payload["evidence_ids"] = _string_list(section_payload.get("evidence_ids") or [])
        section_payload["claim_grounding"] = normalize_claim_grounding(
            section_payload.get("claim_grounding") or []
        )
        normalized_sections.append(section_payload)
    draft["title"] = str(draft.get("title") or "Daily Intelligence Report")
    draft["sections"] = normalized_sections
    metadata = draft.get("metadata")
    draft["metadata"] = dict(metadata) if isinstance(metadata, Mapping) else {}
    return draft


def source_urls_from_draft(draft: dict[str, Any]) -> set[str]:
    urls: set[str] = set()
    for section in draft.get("sections") or []:
        if isinstance(section, Mapping):
            urls.update(_string_list(section.get("sources") or section.get("source_urls") or []))
    return urls


def source_urls_from_evidence(evidence_bundle: Any) -> set[str]:
    urls = set(_string_list(_field_value(evidence_bundle, "source_urls", default=[])))
    source_map = _field_value(evidence_bundle, "source_map", default={})
    if isinstance(source_map, Mapping):
        urls.update(str(url) for url in source_map if url)
    items = _field_value(evidence_bundle, "items", default=[])
    for item in _list_value(items):
        urls.update(_string_list(_field_value(item, "source_urls", default=[])))
        source_url = _field_value(item, "source_url")
        if source_url:
            urls.add(str(source_url))
    return urls


def sources_outside_evidence(
    draft: dict[str, Any],
    evidence_bundle: Any,
) -> list[str]:
    allowed_sources = source_urls_from_evidence(evidence_bundle)
    draft_sources = source_urls_from_draft(draft)
    return sorted(source for source in draft_sources if source not in allowed_sources)


def normalize_claim_grounding(value: Any) -> list[dict[str, Any]]:
    grounded_claims: list[dict[str, Any]] = []
    for item in _list_value(value):
        if not isinstance(item, Mapping):
            continue
        grounded_claims.append(
            {
                "claim_id": str(item.get("claim_id") or ""),
                "text": str(item.get("text") or item.get("claim") or ""),
                "evidence_ids": _string_list(item.get("evidence_ids") or []),
                "source_urls": _string_list(item.get("source_urls") or item.get("sources") or []),
            }
        )
    return grounded_claims
