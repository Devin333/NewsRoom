from __future__ import annotations

import pytest

from business.research.domain.reader_repair import ReaderRepairAttempt, ReaderRepairCandidate
from business.research.reader_repair import ReaderRepairGateSuite


def test_repair_candidate_cannot_decide_memory_or_skill_publication() -> None:
    results = ReaderRepairGateSuite().verify_candidate_payload(
        {
            "repair_summary": "Patch table.",
            "target_region_refs": ["paper://paper-1/table-1"],
            "patch_operations": [{"op": "replace_region", "path": "table-1"}],
            "quality_passed": True,
            "write_memory": True,
            "promote_skill": True,
        }
    )

    assert results[0].passed is False
    assert set(results[0].metadata["forbidden"]) == {"promote_skill", "quality_passed", "write_memory"}


def test_localized_patch_gate_rejects_out_of_region_patch() -> None:
    candidate = ReaderRepairCandidate(
        candidate_id="candidate-1",
        repair_summary="Patch outside the issue.",
        target_region_refs=["paper://paper-1/other"],
        patch_operations=[{"op": "replace_region", "path": "other"}],
        expected_effect="Fix payload.",
        confidence=0.8,
    )

    results = ReaderRepairGateSuite().verify_candidate(candidate, ["paper://paper-1/table-1"])

    assert any(result.gate_name == "ReaderLocalizedPatchGate" and not result.passed for result in results)


def test_repair_attempt_requires_isolated_proposer_and_verifier() -> None:
    candidate = ReaderRepairCandidate(
        candidate_id="candidate-1",
        repair_summary="Patch table cells.",
        target_region_refs=["paper://paper-1/table-1"],
        patch_operations=[{"op": "replace_region", "path": "table-1"}],
        expected_effect="Restore dropped table cells.",
        confidence=0.8,
    )

    with pytest.raises(ValueError, match="isolated subagents"):
        ReaderRepairAttempt(
            attempt_id="attempt-1",
            issue_id="issue-1",
            proposer_subagent_id="repair-agent",
            verifier_subagent_id="repair-agent",
            candidate=candidate,
            context_snapshot_ref="context-snapshot://reader-repair/1",
        )


def test_repair_attempt_rejects_verifier_access_to_proposer_private_notes() -> None:
    candidate = ReaderRepairCandidate(
        candidate_id="candidate-1",
        repair_summary="Patch table cells.",
        target_region_refs=["paper://paper-1/table-1"],
        patch_operations=[{"op": "replace_region", "path": "table-1"}],
        expected_effect="Restore dropped table cells.",
        confidence=0.8,
    )

    with pytest.raises(ValueError, match="private notes"):
        ReaderRepairAttempt(
            attempt_id="attempt-1",
            issue_id="issue-1",
            proposer_subagent_id="reader-repair-proposer",
            verifier_subagent_id="reader-repair-verifier",
            candidate=candidate,
            context_snapshot_ref="context-snapshot://reader-repair/1",
            metadata={"verifier_saw_proposer_private_notes": True},
        )
