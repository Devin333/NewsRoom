from __future__ import annotations

from business.foundation import BusinessQualityCheck, Relation


def check_relation_quality(relations: list[Relation]) -> list[BusinessQualityCheck]:
    return [
        BusinessQualityCheck.create(
            "relations_have_evidence",
            passed=all(relation.evidence_signal_ids for relation in relations),
            severity="error",
            reason="All accepted relations must include evidence_signal_ids.",
            observed={"relation_count": len(relations)},
        )
    ]
