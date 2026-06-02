from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any

from business.foundation.feedback.policy_experiment import PolicyExperimentProfile


PROPOSAL_STATUSES = {"proposed", "approved", "rejected", "applied", "superseded"}


@dataclass(frozen=True)
class ImprovementProposal:
    proposal_id: str
    recommendation_id: str
    board_type: str
    change_type: str
    target_type: str
    target_id: str
    proposed_patch: dict[str, Any]
    risk_level: str
    requires_approval: bool
    status: str
    experiment_profile: PolicyExperimentProfile | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))

    def __post_init__(self) -> None:
        if self.status not in PROPOSAL_STATUSES:
            raise ValueError(f"unsupported proposal status: {self.status}")

    def with_status(self, status: str) -> "ImprovementProposal":
        return replace(self, status=status)

    @property
    def policy_experiment_parameters(self) -> dict[str, Any]:
        if self.experiment_profile is not None:
            return dict(self.experiment_profile.parameters)
        return dict(self.proposed_patch)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["policy_experiment_parameters"] = self.policy_experiment_parameters
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ImprovementProposal":
        proposed_patch = dict(payload.get("proposed_patch") or payload.get("policy_experiment_parameters") or {})
        return cls(
            proposal_id=str(payload["proposal_id"]),
            recommendation_id=str(payload["recommendation_id"]),
            board_type=str(payload["board_type"]),
            change_type=str(payload["change_type"]),
            target_type=str(payload["target_type"]),
            target_id=str(payload["target_id"]),
            proposed_patch=proposed_patch,
            risk_level=str(payload.get("risk_level") or "medium"),
            requires_approval=bool(payload.get("requires_approval", True)),
            status=str(payload.get("status") or "proposed"),
            experiment_profile=(
                PolicyExperimentProfile.from_dict(dict(payload["experiment_profile"]))
                if isinstance(payload.get("experiment_profile"), dict)
                else None
            ),
            created_at=str(payload.get("created_at") or datetime.now(UTC).isoformat().replace("+00:00", "Z")),
        )


__all__ = ["ImprovementProposal", "PROPOSAL_STATUSES"]
