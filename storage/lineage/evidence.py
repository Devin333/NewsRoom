from __future__ import annotations

from typing import Any

from storage.lineage.models import LineageRef


def lineage_refs_from_evidence_bundle(
    bundle: Any,
    *,
    run_id: str,
    workflow_id: str | None = None,
) -> list[LineageRef]:
    payload = _to_dict(bundle)
    refs: dict[str, LineageRef] = {}
    for item in payload.get("items") or []:
        evidence_id = str(item["evidence_id"])
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
    return list(refs.values())


def _add_ref(refs: dict[str, LineageRef], ref: LineageRef | None) -> None:
    if ref is not None:
        refs[str(ref.lineage_id)] = ref


def _to_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return dict(value)
