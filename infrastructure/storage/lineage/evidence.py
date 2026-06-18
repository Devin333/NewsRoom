from __future__ import annotations

from typing import Any

from infrastructure.storage.lineage.models import LineageRef


def lineage_refs_from_evidence_bundle(
    bundle: Any,
    *,
    run_id: str,
    workflow_id: str | None = None,
) -> list[LineageRef]:
    payload = _to_dict(bundle)
    refs: dict[str, LineageRef] = {}
    evidence_ids: list[str] = []
    claim_ids: list[str] = []
    for item in payload.get("items") or []:
        evidence_id = str(item["evidence_id"])
        evidence_ids.append(evidence_id)
        source_url = item.get("source_url")
        source_lineage = dict((item.get("metadata") or {}).get("source_lineage") or {})
        metadata = {
            "bundle_id": payload.get("bundle_id"),
            "workflow_id": workflow_id,
            "evidence_title": item.get("title"),
        }
        _add_ref(
            refs,
            LineageRef(
                run_id=run_id,
                source_type="source_url",
                source_id=str(source_url),
                target_type="evidence",
                target_id=evidence_id,
                relation_type="source_url_to_evidence",
                metadata=metadata,
            )
            if source_url
            else None,
        )
        for source_type, key, relation_type in [
            ("source_item", "source_item_id", "source_item_to_evidence"),
            ("normalized_source_item", "normalized_item_id", "normalized_item_to_evidence"),
            ("ranked_source_item", "ranked_item_id", "ranked_item_to_evidence"),
        ]:
            value = source_lineage.get(key)
            _add_ref(
                refs,
                LineageRef(
                    run_id=run_id,
                    source_type=source_type,
                    source_id=str(value),
                    target_type="evidence",
                    target_id=evidence_id,
                    relation_type=relation_type,
                    metadata={**metadata, "source_lineage": source_lineage},
                )
                if value
                else None,
            )
    for evidence_id in evidence_ids:
        _add_ref(
            refs,
            LineageRef(
                run_id=run_id,
                source_type="evidence_bundle",
                source_id=str(payload.get("bundle_id") or run_id),
                target_type="evidence",
                target_id=evidence_id,
                relation_type="bundle_to_evidence",
                metadata={"workflow_id": workflow_id},
            ),
        )
    for claim in payload.get("candidate_claims") or []:
        if not isinstance(claim, dict):
            continue
        claim_id = str(claim.get("claim_id") or "").strip()
        if not claim_id:
            continue
        claim_ids.append(claim_id)
        for evidence_id in _string_list(claim.get("source_evidence_ids") or []):
            _add_ref(
                refs,
                LineageRef(
                    run_id=run_id,
                    source_type="evidence",
                    source_id=evidence_id,
                    target_type="claim",
                    target_id=claim_id,
                    relation_type="evidence_to_claim",
                    metadata={
                        "bundle_id": payload.get("bundle_id"),
                        "workflow_id": workflow_id,
                        "claim_text": claim.get("text"),
                    },
                ),
            )
    report_id = str(payload.get("report_id") or payload.get("bundle_id") or run_id)
    for claim_id in claim_ids:
        _add_ref(
            refs,
            LineageRef(
                run_id=run_id,
                source_type="claim",
                source_id=claim_id,
                target_type="report",
                target_id=report_id,
                relation_type="claim_to_report",
                metadata={"bundle_id": payload.get("bundle_id"), "workflow_id": workflow_id},
            ),
        )
    return list(refs.values())


def quality_lineage_summary(
    *,
    run_id: str,
    report_id: str | None,
    claims: list[dict[str, Any]],
    quality_results: list[dict[str, Any]],
) -> dict[str, Any]:
    supporting_evidence_ids = sorted(
        {
            str(evidence_id)
            for claim in claims
            for evidence_id in claim.get("supporting_evidence_ids", [])
            if evidence_id
        }
    )
    rejecting_evidence_ids = sorted(
        {
            str(evidence_id)
            for claim in claims
            for evidence_id in claim.get("rejecting_evidence_ids", [])
            if evidence_id
        }
    )
    return {
        "report_id": report_id or run_id,
        "claim_count": len(claims),
        "quality_result_count": len(quality_results),
        "claims": [_claim_lineage_view(claim) for claim in claims],
        "supporting_evidence_ids": supporting_evidence_ids,
        "rejecting_evidence_ids": rejecting_evidence_ids,
    }


def _claim_lineage_view(claim: dict[str, Any]) -> dict[str, Any]:
    return {
        "claim_id": str(claim.get("claim_id") or ""),
        "status": str(claim.get("status") or "unknown"),
        "text": str(claim.get("text") or claim.get("claim") or ""),
        "supporting_evidence_ids": [str(value) for value in claim.get("supporting_evidence_ids", [])],
        "supporting_sources": [str(value) for value in claim.get("supporting_sources", [])],
        "rejecting_evidence_ids": [str(value) for value in claim.get("rejecting_evidence_ids", [])],
        "rejecting_sources": [str(value) for value in claim.get("rejecting_sources", [])],
    }


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and str(item)]
    return []


def _add_ref(refs: dict[str, LineageRef], ref: LineageRef | None) -> None:
    if ref is not None:
        refs[str(ref.lineage_id)] = ref


def _to_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return dict(value)
