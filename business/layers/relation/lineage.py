from __future__ import annotations

from typing import Any

from storage.lineage import LineageRef, lineage_refs_from_evidence_bundle


def evidence_bundle_lineage_extractor(
    *,
    output: dict[str, Any],
    run_id: str,
    workflow_id: str,
) -> list[LineageRef]:
    evidence_bundle = output.get("evidence_bundle")
    if evidence_bundle is None:
        return []
    return lineage_refs_from_evidence_bundle(
        evidence_bundle,
        run_id=run_id,
        workflow_id=workflow_id,
    )
