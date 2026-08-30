from __future__ import annotations

from datetime import datetime, timezone as _tz
UTC = _tz.utc

from backend.foundation.models import (
    BusinessPolicyCandidate,
    BusinessPolicyProfile,
    BusinessRegressionGuardResult,
)


def activate_policy_candidate(
    candidate: BusinessPolicyCandidate,
    guard_result: BusinessRegressionGuardResult,
    *,
    manual_approval: bool,
) -> BusinessPolicyProfile:
    if not manual_approval:
        raise ValueError("manual approval is required to activate a policy candidate")
    if not guard_result.passed or guard_result.status == "block":
        raise ValueError("blocked policy candidate cannot be activated")
    return candidate.profile.model_copy(
        update={
            "status": "active",
            "activated_at": datetime.now(UTC),
        }
    )


__all__ = ["activate_policy_candidate"]
