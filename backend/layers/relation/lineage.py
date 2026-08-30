from __future__ import annotations

from typing import Any

from framework.shared.graph_identity import GraphRunIdentity

from backend.layers.relation.lineage_refs import RelationLineageRef


def evidence_bundle_lineage_extractor(
    *,
    output: dict[str, Any],
    graph_identity: GraphRunIdentity,
) -> list[RelationLineageRef]:
    evidence_bundle = output.get("evidence_bundle")
    if evidence_bundle is None:
        return []
    return lineage_refs_from_evidence_bundle(
        evidence_bundle,
        graph_identity=graph_identity,
    )


def lineage_refs_from_evidence_bundle(
    bundle: Any,
    *,
    graph_identity: GraphRunIdentity,
) -> list[RelationLineageRef]:
    if not isinstance(graph_identity, GraphRunIdentity):
        raise TypeError("graph_identity must be GraphRunIdentity")
    payload = _to_dict(bundle)
    refs: dict[str, RelationLineageRef] = {}
    evidence_ids: list[str] = []
    claim_ids: list[str] = []
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        evidence_id = str(item.get("evidence_id") or "").strip()
        if not evidence_id:
            continue
        evidence_ids.append(evidence_id)
        source_url = item.get("source_url")
        source_lineage = dict((item.get("metadata") or {}).get("source_lineage") or {})
        metadata = {
            "bundle_id": payload.get("bundle_id"),
            "graph_identity": graph_identity.to_dict(),
            "evidence_title": item.get("title"),
        }
        _add_ref(
            refs,
            RelationLineageRef(
                graph_identity=graph_identity,
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
                RelationLineageRef(
                    graph_identity=graph_identity,
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
            RelationLineageRef(
                graph_identity=graph_identity,
                source_type="evidence_bundle",
                source_id=str(payload.get("bundle_id") or graph_identity.run_id),
                target_type="evidence",
                target_id=evidence_id,
                relation_type="bundle_to_evidence",
                metadata={"graph_identity": graph_identity.to_dict()},
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
                RelationLineageRef(
                    graph_identity=graph_identity,
                    source_type="evidence",
                    source_id=evidence_id,
                    target_type="claim",
                    target_id=claim_id,
                    relation_type="evidence_to_claim",
                    metadata={
                        "bundle_id": payload.get("bundle_id"),
                        "graph_identity": graph_identity.to_dict(),
                        "claim_text": claim.get("text"),
                    },
                ),
            )
    report_id = str(
        payload.get("report_id")
        or payload.get("bundle_id")
        or graph_identity.run_id
    )
    for claim_id in claim_ids:
        _add_ref(
            refs,
            RelationLineageRef(
                graph_identity=graph_identity,
                source_type="claim",
                source_id=claim_id,
                target_type="report",
                target_id=report_id,
                relation_type="claim_to_report",
                metadata={"bundle_id": payload.get("bundle_id"), "graph_identity": graph_identity.to_dict()},
            ),
        )
    return list(refs.values())


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and str(item)]
    return []


def _add_ref(refs: dict[str, RelationLineageRef], ref: RelationLineageRef | None) -> None:
    if ref is not None:
        refs[str(ref.lineage_id)] = ref


def _to_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return dict(value)
