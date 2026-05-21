from __future__ import annotations

from business.foundation import (
    BusinessQualityCheck,
    BusinessRegressionGuardResult,
    build_stable_id,
)


def guard_cross_board_insight(*, evidence_count: int, board_support_count: int, confidence: float) -> BusinessRegressionGuardResult:
    checks = [
        BusinessQualityCheck.create(
            "cross_board_has_evidence",
            passed=evidence_count > 0,
            severity="block",
            reason="Cross-board insight must have evidence relations.",
            observed={"evidence_count": evidence_count},
        ),
        BusinessQualityCheck.create(
            "cross_board_has_multi_board_support",
            passed=board_support_count >= 2,
            severity="block",
            reason="Cross-board insight must have at least two board supports.",
            observed={"board_support_count": board_support_count},
        ),
        BusinessQualityCheck.create(
            "cross_board_confidence_threshold",
            passed=confidence >= 0.65,
            severity="warning",
            reason="Weak relation chain cannot produce strong insight.",
            observed={"confidence": confidence},
        ),
    ]
    blocking = [check.reason for check in checks if not check.passed and check.severity == "block"]
    passed = not blocking
    return BusinessRegressionGuardResult(
        guard_id=build_stable_id("cross_guard", evidence_count, board_support_count, confidence),
        status="pass" if passed else "block",
        passed=passed,
        checks=checks,
        blocking_reasons=blocking,
        warnings=[check.reason for check in checks if not check.passed and check.severity == "warning"],
    )
