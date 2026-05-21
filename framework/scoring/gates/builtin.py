from __future__ import annotations

from framework.scoring.gates.models import GateAction, GateSpec


def build_default_gate_specs() -> dict[str, GateSpec]:
    return {
        "requires_evidence": GateSpec(
            gate_id="requires_evidence",
            action=GateAction.BLOCK,
            feature="evidence_strength",
            operator="gt",
            threshold=0.0,
            severity="error",
            reason="requires_evidence failed",
        ),
        "score_cap_no_evidence": GateSpec(
            gate_id="score_cap_no_evidence",
            action=GateAction.CAP,
            feature="evidence_strength",
            operator="gt",
            threshold=0.0,
            score_cap=0.35,
            severity="warning",
            reason="score capped because evidence is missing",
        ),
        "low_confidence_review": GateSpec(
            gate_id="low_confidence_review",
            action=GateAction.REVIEW,
            feature="confidence",
            operator="gte",
            threshold=0.45,
            severity="warning",
            reason="low confidence requires review",
        ),
        "block_contradiction": GateSpec(
            gate_id="block_contradiction",
            action=GateAction.BLOCK,
            feature="contradiction_penalty",
            operator="eq",
            threshold=0.0,
            severity="error",
            reason="contradiction detected",
        ),
        "single_source_cap": GateSpec(
            gate_id="single_source_cap",
            action=GateAction.CAP,
            feature="source_count",
            operator="gt",
            threshold=1.0,
            score_cap=0.7,
            severity="warning",
            reason="single source caps score",
        ),
        "duplicate_penalty": GateSpec(
            gate_id="duplicate_penalty",
            action=GateAction.PENALTY,
            feature="duplicate_count",
            operator="eq",
            threshold=0.0,
            penalty=0.15,
            severity="warning",
            reason="duplicate evidence penalty",
        ),
    }
