from __future__ import annotations

from business.foundation.models import (
    BusinessPolicyCandidate,
    BusinessQualityCheck,
    BusinessRegressionGuardResult,
)
from business.foundation.primitives import build_stable_id


class RegressionGuardRunner:
    def run(
        self,
        candidate: BusinessPolicyCandidate,
        checks: list[BusinessQualityCheck] | None = None,
    ) -> BusinessRegressionGuardResult:
        guard_checks = checks or [
            BusinessQualityCheck.create(
                "candidate_has_version",
                passed=bool(candidate.profile.version),
                severity="block",
                reason="candidate policy must have a version",
            ),
            BusinessQualityCheck.create(
                "candidate_not_auto_active",
                passed=candidate.profile.status != "active",
                severity="block",
                reason="candidate must not be active before manual activation",
            ),
        ]
        blocking = [check.reason or check.check_type for check in guard_checks if not check.passed and check.severity == "block"]
        warnings = [check.reason or check.check_type for check in guard_checks if not check.passed and check.severity == "warning"]
        passed = not blocking
        return BusinessRegressionGuardResult(
            guard_id=build_stable_id("guard", candidate.candidate_id, [(check.check_type, check.passed) for check in guard_checks]),
            candidate_id=candidate.candidate_id,
            status="pass" if passed else "block",
            passed=passed,
            checks=guard_checks,
            blocking_reasons=blocking,
            warnings=warnings,
        )


__all__ = ["RegressionGuardRunner"]
