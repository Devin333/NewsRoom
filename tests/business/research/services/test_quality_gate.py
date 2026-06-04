from __future__ import annotations

from business.research.domain import GateResult
from business.research.services import ResearchQualityGate


def test_quality_gate_collects_failed_gate_flags() -> None:
    result = ResearchQualityGate().evaluate(
        target_id="paper-1",
        target_type="summary",
        gate_results=[
            GateResult.pass_("SchemaGate"),
            GateResult.fail("ClaimEvidenceGate", "claim requires evidence"),
        ],
    )

    payload = result.to_dict()

    assert payload["passed"] is False
    assert payload["quality_flags"][0]["flag_type"] == "claimevidencegate"
