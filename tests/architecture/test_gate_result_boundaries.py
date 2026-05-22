from __future__ import annotations


def test_gate_result_types_have_distinct_runtime_ownership() -> None:
    from framework.governance import GateResult as GovernanceGateResult
    from framework.scoring.gates import GateResult as ScoringGateResult
    from framework.skills.quality import SkillQualityGateResult

    assert GovernanceGateResult is not ScoringGateResult
    assert GovernanceGateResult.__module__ == "framework.governance.gate"
    assert ScoringGateResult.__module__ == "framework.scoring.gates.models"
    assert SkillQualityGateResult.__module__ == "framework.skills.quality.gates"
