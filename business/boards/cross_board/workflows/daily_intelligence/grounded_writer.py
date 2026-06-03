from __future__ import annotations

import re
from typing import Any

from business.boards.cross_board.workflows.daily_intelligence.grounded_writer_evidence_view import (
    GroundedWriterEvidenceBundleView,
)
from business.layers.relation.evidence.models import VerifiedFindings


def normalize_daily_writer_output(
    *,
    output: dict[str, Any],
    output_key: str,
    inputs: dict[str, Any],
) -> dict[str, Any]:
    report_draft = output.get(output_key)
    if not isinstance(report_draft, dict):
        return output
    evidence_view = GroundedWriterEvidenceBundleView.from_inputs(inputs)
    verified_findings = _verified_findings_from_inputs(inputs)
    if evidence_view is None or verified_findings is None:
        return output
    normalized_output = dict(output)
    normalized_output[output_key] = _normalized_writer_report_draft(
        report_draft,
        evidence_view=evidence_view,
        verified_findings=verified_findings,
    )
    return normalized_output


def _normalized_writer_report_draft(
    report_draft: dict[str, Any],
    *,
    evidence_view: GroundedWriterEvidenceBundleView,
    verified_findings: VerifiedFindings,
) -> dict[str, Any]:
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
        evidence_selection = evidence_view.select(claim.supporting_evidence_ids)
        if not evidence_selection.evidence_ids:
            continue
        source_urls = evidence_selection.source_urls(claim.supporting_sources)
        if not source_urls:
            continue
        title = str(
            evidence_selection.primary_title or claim.claim or claim.claim_id
        ).strip()
        content = str(claim.claim).strip()
        if not title or not content:
            continue
        normalized_sections.append(
            {
                "section_id": _section_slug(title, claim.claim_id),
                "title": title,
                "content": content,
                "sources": source_urls,
                "evidence_ids": list(evidence_selection.evidence_ids),
                "claim_grounding": [
                    {
                        "claim_id": claim.claim_id,
                        "text": content,
                        "evidence_ids": list(evidence_selection.evidence_ids),
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


def _verified_findings_from_inputs(inputs: dict[str, Any]) -> VerifiedFindings | None:
    value = inputs.get("verified_findings")
    if isinstance(value, VerifiedFindings):
        return value
    return None


def _section_slug(title: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", title.casefold()).strip("_")
    return slug or fallback
