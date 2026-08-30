from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any

from backend.foundation.feedback.policy_experiment import PolicyExperimentProfile


PROPOSAL_STATUSES = {"proposed", "approved", "rejected", "applied", "superseded"}


@dataclass(frozen=True, init=False)
class ImprovementProposal:
    proposal_id: str
    recommendation_id: str
    board_type: str
    change_type: str
    target_type: str
    target_id: str
    policy_experiment_parameters: dict[str, Any]
    risk_level: str
    requires_approval: bool
    status: str
    experiment_profile: PolicyExperimentProfile | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))

    def __init__(
        self,
        proposal_id: str,
        recommendation_id: str,
        board_type: str,
        change_type: str,
        target_type: str,
        target_id: str,
        *,
        policy_experiment_parameters: dict[str, Any] | None = None,
        proposed_patch: dict[str, Any] | None = None,
        risk_level: str,
        requires_approval: bool,
        status: str,
        experiment_profile: PolicyExperimentProfile | None = None,
        created_at: str | None = None,
    ) -> None:
        resolved_parameters = dict(policy_experiment_parameters or proposed_patch or {})
        object.__setattr__(self, "proposal_id", str(proposal_id))
        object.__setattr__(self, "recommendation_id", str(recommendation_id))
        object.__setattr__(self, "board_type", str(board_type))
        object.__setattr__(self, "change_type", str(change_type))
        object.__setattr__(self, "target_type", str(target_type))
        object.__setattr__(self, "target_id", str(target_id))
        object.__setattr__(self, "policy_experiment_parameters", resolved_parameters)
        object.__setattr__(self, "risk_level", str(risk_level))
        object.__setattr__(self, "requires_approval", bool(requires_approval))
        object.__setattr__(self, "status", str(status))
        object.__setattr__(self, "experiment_profile", experiment_profile)
        object.__setattr__(
            self,
            "created_at",
            str(created_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")),
        )
        self._validate_status()

    def _validate_status(self) -> None:
        if self.status not in PROPOSAL_STATUSES:
            raise ValueError(f"unsupported proposal status: {self.status}")

    def with_status(self, status: str) -> "ImprovementProposal":
        return replace(self, status=status)

    @property
    def proposed_patch(self) -> dict[str, Any]:
        return dict(self.policy_experiment_parameters)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "proposal_id": self.proposal_id,
            "recommendation_id": self.recommendation_id,
            "board_type": self.board_type,
            "change_type": self.change_type,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "policy_experiment_parameters": dict(self.policy_experiment_parameters),
            "risk_level": self.risk_level,
            "requires_approval": self.requires_approval,
            "status": self.status,
            "experiment_profile": (
                self.experiment_profile.to_dict() if self.experiment_profile is not None else None
            ),
            "created_at": self.created_at,
        }
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ImprovementProposal":
        policy_experiment_parameters = dict(
            payload.get("policy_experiment_parameters") or payload.get("proposed_patch") or {}
        )
        return cls(
            proposal_id=str(payload["proposal_id"]),
            recommendation_id=str(payload["recommendation_id"]),
            board_type=str(payload["board_type"]),
            change_type=str(payload["change_type"]),
            target_type=str(payload["target_type"]),
            target_id=str(payload["target_id"]),
            policy_experiment_parameters=policy_experiment_parameters,
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
