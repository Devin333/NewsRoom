from __future__ import annotations

from business.foundation import (
    BusinessFeedbackEvent,
    BusinessPolicySnapshot,
    BusinessQualityCheck,
    BusinessQualitySnapshot,
    quality_snapshot_from_checks,
)
from business.layers.output import BoardOutput


class BoardQualityService:
    def build_summary(self, output: BoardOutput) -> BusinessQualitySnapshot:
        checks = [
            BusinessQualityCheck.create(
                "board_has_policy_compatible_cards",
                passed=all(card.ranking_reason for card in output.cards),
                severity="error",
                reason="Every board card must include ranking_reason.",
                observed={"card_count": len(output.cards)},
            ),
            BusinessQualityCheck.create(
                "top_cards_have_evidence",
                passed=all(card.evidence_refs for card in output.cards[:3]),
                severity="error",
                reason="Top cards must include evidence_refs.",
                observed={"top_card_count": len(output.cards[:3])},
            ),
        ]
        score = 1.0 if all(check.passed for check in checks) else 0.5
        return quality_snapshot_from_checks(checks, score=score, confidence=0.8)

    def feedback_candidates(
        self,
        output: BoardOutput,
        quality_summary: BusinessQualitySnapshot,
        policy_snapshot: BusinessPolicySnapshot,
    ) -> list[BusinessFeedbackEvent]:
        events: list[BusinessFeedbackEvent] = []
        for check in quality_summary.checks:
            if check.passed:
                continue
            events.append(
                BusinessFeedbackEvent.create(
                    target_object_type="board_run",
                    target_object_id=output.board_type.value,
                    target_layer="board",
                    board_type=output.board_type.value,
                    feedback_type=check.check_type,
                    severity=check.severity,
                    observed=check.observed,
                    expected=check.expected,
                    error_tags=[check.check_type],
                    evidence_refs=list(check.evidence_refs),
                    related_policy_profile_id=policy_snapshot.profiles[0].profile_id if policy_snapshot.profiles else None,
                    related_policy_profile_version=policy_snapshot.profiles[0].version if policy_snapshot.profiles else None,
                )
            )
        return events


__all__ = ["BoardQualityService"]
