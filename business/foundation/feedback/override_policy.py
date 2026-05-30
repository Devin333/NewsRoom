from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any


SUPPORTED_OVERRIDE_TYPES = {
    "ranking_weight_override",
    "policy_threshold_override",
    "source_reliability_override",
    "skill_prompt_hint_override",
    "board_quality_gate_override",
}


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


@dataclass(frozen=True)
class BoardImprovementContext:
    run_id: str
    board_type: str
    applied_overrides: list[dict[str, Any]] = field(default_factory=list)
    skipped_overrides: list[dict[str, Any]] = field(default_factory=list)
    proposal_ids: list[str] = field(default_factory=list)
    measurement_plan: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = ["BoardImprovementContext", "ImprovementOverride", "SUPPORTED_OVERRIDE_TYPES"]
