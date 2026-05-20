from __future__ import annotations

import re
from typing import Any

from business.layers.relation.evidence.models import EvidenceBundle, EvidenceItem, VerifiedFindings


def normalize_daily_writer_output(
    *,
    output: dict[str, Any],
    output_key: str,
    inputs: dict[str, Any],
) -> dict[str, Any]:
    report_draft = output.get(output_key)
    if not isinstance(report_draft, dict):
        return output
    evidence_bundle = _coerce_evidence_bundle_from_inputs(inputs)
    verified_findings = _verified_findings_from_inputs(inputs)
    if evidence_bundle is None or verified_findings is None:
        return output
    normalized_output = dict(output)
    normalized_output[output_key] = _normalized_writer_report_draft(
        report_draft,
        evidence_bundle=evidence_bundle,
        verified_findings=verified_findings,
    )
    return normalized_output


def _normalized_writer_report_draft(
    report_draft: dict[str, Any],
    *,
    evidence_bundle: EvidenceBundle,
    verified_findings: VerifiedFindings,
) -> dict[str, Any]:
    evidence_by_id = {item.evidence_id: item for item in evidence_bundle.items if item.evidence_id}
    accepted_claims = [
        claim
        for claim in verified_findings.accepted_claims
        if claim.supporting_evidence_ids and claim.supporting_sources
    ]
    if not accepted_claims:
        return report_draft
    normalized_sections: list[dict[str, Any]] = []
    seen_claim_ids: set[str] = set()
    for claim in accepted_claims:
        if claim.claim_id in seen_claim_ids:
            continue
        seen_claim_ids.add(claim.claim_id)
        evidence_ids = [
            evidence_id
            for evidence_id in claim.supporting_evidence_ids
            if evidence_id in evidence_by_id
        ]
        if not evidence_ids:
            continue
        grounded_items = [evidence_by_id[evidence_id] for evidence_id in evidence_ids]
        source_urls = _stable_source_urls(
            [
                *claim.supporting_sources,
                *[
                    source_url
                    for item in grounded_items
                    for source_url in (item.source_urls or ([item.source_url] if item.source_url else []))
                ],
            ]
        )
        if not source_urls:
            continue
        primary_item = grounded_items[0]
        title = str(primary_item.title or claim.claim or claim.claim_id).strip()
        content = str(claim.claim).strip()
        if not title or not content:
            continue
        normalized_sections.append(
            {
                "section_id": _section_slug(title, claim.claim_id),
                "title": title,
                "content": content,
                "sources": source_urls,
                "evidence_ids": evidence_ids,
                "claim_grounding": [
                    {
                        "claim_id": claim.claim_id,
                        "text": content,
                        "evidence_ids": evidence_ids,
                        "source_urls": source_urls,
                    }
                ],
            }
        )
    if not normalized_sections:
        return report_draft
    normalized_draft = dict(report_draft)
    normalized_draft["sections"] = normalized_sections
    metadata = dict(normalized_draft.get("metadata") or {})
    metadata["writer_normalized_from_verified_findings"] = True
    normalized_draft["metadata"] = metadata
    return normalized_draft


def _coerce_evidence_bundle_from_inputs(inputs: dict[str, Any]) -> EvidenceBundle | None:
    value = inputs.get("evidence_bundle") or inputs.get("bundle")
    if isinstance(value, EvidenceBundle):
        return value
    if not isinstance(value, dict):
        return None
    return _build_evidence_bundle_from_dict(value)


def _build_evidence_bundle_from_dict(value: dict[str, Any]) -> EvidenceBundle | None:
    raw_items = value.get("items")
    if not isinstance(raw_items, list):
        return None
    items: list[EvidenceItem] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        items.append(
            EvidenceItem(
                evidence_id=str(raw_item.get("evidence_id") or ""),
                source_url=str(raw_item.get("source_url") or ""),
                title=str(raw_item.get("title") or ""),
                summary=str(raw_item.get("summary") or raw_item.get("title") or ""),
                confidence=float(raw_item.get("confidence", 0.0)),
                source_id=str(raw_item.get("source_id") or ""),
                source_urls=[str(url) for url in raw_item.get("source_urls", []) if url],
                metadata=dict(raw_item.get("metadata") or {}),
            )
        )
    return EvidenceBundle(
        bundle_id=str(value.get("bundle_id") or "agent_input"),
        items=items,
        source_map={
            str(key): [str(item) for item in source_items]
            for key, source_items in dict(value.get("source_map") or {}).items()
        },
        missing_information=[str(item) for item in value.get("missing_information", [])],
        coverage_notes=[str(item) for item in value.get("coverage_notes", [])],
        metadata=dict(value.get("metadata") or {}),
    )


def _verified_findings_from_inputs(inputs: dict[str, Any]) -> VerifiedFindings | None:
    value = inputs.get("verified_findings")
    if isinstance(value, VerifiedFindings):
        return value
    return None


def _stable_source_urls(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _section_slug(title: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", title.casefold()).strip("_")
    return slug or fallback
