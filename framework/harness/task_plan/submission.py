from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.task_plan.canonical import (
    canonical_payload_checksum,
    checksum,
    exact_keys,
    identifier,
    required_text,
    thaw_mapping,
)
from framework.shared.time import parse_datetime

if TYPE_CHECKING:
    from framework.harness.task_plan.store import TaskPlanEvent


CANDIDATE_DEDUP_IDENTITY_SCHEMA = "newsroom.harness-candidate-dedup-identity/v1"
CANDIDATE_SUBMISSION_SCHEMA = "newsroom.harness-candidate-submission/v1"


@dataclass(frozen=True, slots=True)
class CandidateDedupIdentity:
    """Stable parent-action identity for one candidate submission."""

    run_id: str
    stage_id: str
    parent_turn_id: str
    action_correlation_id: str
    schema_version: str = CANDIDATE_DEDUP_IDENTITY_SCHEMA
    dedup_key: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", identifier(self.run_id, "run_id"))
        object.__setattr__(self, "stage_id", identifier(self.stage_id, "stage_id"))
        object.__setattr__(
            self,
            "parent_turn_id",
            identifier(self.parent_turn_id, "parent_turn_id"),
        )
        object.__setattr__(
            self,
            "action_correlation_id",
            identifier(self.action_correlation_id, "action_correlation_id"),
        )
        if self.schema_version != CANDIDATE_DEDUP_IDENTITY_SCHEMA:
            raise HarnessValidationError(
                "unsupported candidate dedup identity schema",
                code="candidate_submission_schema_invalid",
            )
        object.__setattr__(
            self,
            "dedup_key",
            canonical_payload_checksum(self.checksum_projection()),
        )

    def checksum_projection(self) -> dict[str, str]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "stage_id": self.stage_id,
            "parent_turn_id": self.parent_turn_id,
            "action_correlation_id": self.action_correlation_id,
        }

    def to_dict(self) -> dict[str, str]:
        return {**self.checksum_projection(), "dedup_key": self.dedup_key}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CandidateDedupIdentity":
        payload = exact_keys(
            value,
            required=frozenset(
                {
                    "schema_version",
                    "run_id",
                    "stage_id",
                    "parent_turn_id",
                    "action_correlation_id",
                    "dedup_key",
                }
            ),
            model=cls.__name__,
        )
        supplied = checksum(payload.pop("dedup_key"), "dedup_key")
        identity = cls(**payload)
        if supplied != identity.dedup_key:
            raise HarnessValidationError(
                "candidate dedup identity checksum does not match canonical content",
                code="candidate_submission_checksum_mismatch",
            )
        return identity


@dataclass(frozen=True, slots=True)
class CandidateSubmission:
    """Durable mapping from a parent action to one immutable PlanCandidate."""

    identity: CandidateDedupIdentity
    candidate_checksum: str
    candidate_ref: str
    accepted_at: str
    schema_version: str = CANDIDATE_SUBMISSION_SCHEMA
    submission_id: str = field(init=False)
    plan_id: str = field(init=False)
    record_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.identity, CandidateDedupIdentity):
            raise TypeError("identity must be CandidateDedupIdentity")
        object.__setattr__(
            self,
            "candidate_checksum",
            checksum(self.candidate_checksum, "candidate_checksum"),
        )
        object.__setattr__(self, "candidate_ref", checksum(self.candidate_ref, "candidate_ref"))
        accepted_at = required_text(self.accepted_at, "accepted_at")
        parsed = parse_datetime(accepted_at)
        if parsed is None or parsed.tzinfo is None or parsed.utcoffset() is None:
            raise HarnessValidationError(
                "candidate submission accepted_at must be an RFC3339 timezone-aware timestamp",
                code="candidate_submission_timestamp_invalid",
            )
        object.__setattr__(self, "accepted_at", accepted_at)
        if self.schema_version != CANDIDATE_SUBMISSION_SCHEMA:
            raise HarnessValidationError(
                "unsupported candidate submission schema",
                code="candidate_submission_schema_invalid",
            )
        digest = self.identity.dedup_key.removeprefix("sha256:")
        object.__setattr__(self, "submission_id", f"candidate-submission-{digest}")
        plan_digest = canonical_payload_checksum(
            {
                "dedup_key": self.identity.dedup_key,
                "candidate_ref": self.candidate_ref,
            }
        ).removeprefix("sha256:")
        object.__setattr__(self, "plan_id", f"candidate-plan-{plan_digest}")
        object.__setattr__(
            self,
            "record_checksum",
            canonical_payload_checksum(self.checksum_projection()),
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "identity": self.identity.to_dict(),
            "candidate_checksum": self.candidate_checksum,
            "candidate_ref": self.candidate_ref,
            "accepted_at": self.accepted_at,
            "submission_id": self.submission_id,
            "plan_id": self.plan_id,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "record_checksum": self.record_checksum}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CandidateSubmission":
        payload = exact_keys(
            value,
            required=frozenset(
                {
                    "schema_version",
                    "identity",
                    "candidate_checksum",
                    "candidate_ref",
                    "accepted_at",
                    "submission_id",
                    "plan_id",
                    "record_checksum",
                }
            ),
            model=cls.__name__,
        )
        supplied_submission_id = identifier(payload.pop("submission_id"), "submission_id")
        supplied_plan_id = identifier(payload.pop("plan_id"), "plan_id")
        supplied_checksum = checksum(payload.pop("record_checksum"), "record_checksum")
        payload["identity"] = CandidateDedupIdentity.from_dict(payload["identity"])
        submission = cls(**payload)
        if supplied_submission_id != submission.submission_id or supplied_plan_id != submission.plan_id:
            raise HarnessValidationError(
                "candidate submission stable identity does not match canonical content",
                code="candidate_submission_checksum_mismatch",
            )
        if supplied_checksum != submission.record_checksum:
            raise HarnessValidationError(
                "candidate submission checksum does not match canonical content",
                code="candidate_submission_checksum_mismatch",
            )
        return submission


def submissions_from_events(events: Sequence["TaskPlanEvent"]) -> tuple[CandidateSubmission, ...]:
    """Load and validate submission records embedded in candidate-build events."""

    records: dict[str, CandidateSubmission] = {}
    for event in events:
        if event.event_type != "PLAN_CANDIDATE_BUILT":
            continue
        payload = thaw_mapping(event.payload)
        raw_submission = payload.get("submission")
        if raw_submission is None:
            continue
        if not isinstance(raw_submission, Mapping):
            raise HarnessValidationError(
                "candidate submission event is malformed",
                code="candidate_submission_event_invalid",
            )
        submission = CandidateSubmission.from_dict(raw_submission)
        candidate_ref = payload.get("candidate_ref")
        if (
            candidate_ref != submission.candidate_ref
            or event.input_checksum != submission.candidate_ref
            or event.run_id != submission.identity.run_id
            or event.stage_id != submission.identity.stage_id
        ):
            raise HarnessValidationError(
                "candidate submission event does not match its durable identity",
                code="candidate_submission_event_invalid",
            )
        existing = records.get(submission.identity.dedup_key)
        if existing is not None:
            raise HarnessValidationError(
                "candidate submission history contains duplicate dedup identity",
                code="CANDIDATE_IDEMPOTENCY_CONFLICT",
                details={"dedup_key": submission.identity.dedup_key},
            )
        records[submission.identity.dedup_key] = submission
    return tuple(sorted(records.values(), key=lambda item: item.submission_id))


__all__ = [
    "CANDIDATE_DEDUP_IDENTITY_SCHEMA",
    "CANDIDATE_SUBMISSION_SCHEMA",
    "CandidateDedupIdentity",
    "CandidateSubmission",
    "submissions_from_events",
]
