from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any

from business.foundation.feedback.policy_experiment import (
    LEGACY_POLICY_EXPERIMENT_CHANGE_TYPES,
    PolicyExperimentApplicationContext,
    is_legacy_policy_experiment_change_type,
)

SUPPORTED_OVERRIDE_TYPES = LEGACY_POLICY_EXPERIMENT_CHANGE_TYPES


@dataclass(frozen=True)
class ImprovementOverride:
    override_id: str
    proposal_id: str
    board_type: str
    override_type: str
    target_id: str
    patch: dict[str, Any]
    applied_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


LegacyPolicyExperimentPatch = ImprovementOverride


BoardImprovementContext = PolicyExperimentApplicationContext


__all__ = [
    "BoardImprovementContext",
    "ImprovementOverride",
    "LEGACY_POLICY_EXPERIMENT_CHANGE_TYPES",
    "LegacyPolicyExperimentPatch",
    "SUPPORTED_OVERRIDE_TYPES",
    "is_legacy_policy_experiment_change_type",
]
