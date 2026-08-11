from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from framework.harness.context.compaction_models import ContextLossRisk
from framework.harness.context.verified_common import (
    identity,
    reject_fields,
    required_text,
    strict_payload,
    text_tuple,
)
from framework.harness.control_plane.errors import HarnessValidationError


CONTEXT_SUMMARY_CANDIDATE_SCHEMA_REVISION = "newsroom.context-summary-candidate/v1"
CONTEXT_SUMMARY_CLAIM_SCHEMA_REVISION = "newsroom.context-summary-claim/v1"


@dataclass(frozen=True)
class ContextSummaryClaim:
    supporting_refs: tuple[str, ...]
    claim_id: str | None = None
    schema_revision: str = CONTEXT_SUMMARY_CLAIM_SCHEMA_REVISION
    identity_checksum: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "supporting_refs",
            text_tuple(
                self.supporting_refs,
                field="supporting_refs",
                required=True,
            ),
        )
        object.__setattr__(
            self,
            "schema_revision",
            required_text(self.schema_revision, field="schema_revision"),
        )
        expected_id, checksum = identity("context-summary-claim", self.identity_projection())
        if self.claim_id is not None and self.claim_id != expected_id:
            raise HarnessValidationError("claim_id does not match claim support identity")
        if self.identity_checksum is not None and self.identity_checksum != checksum:
            raise HarnessValidationError("claim identity checksum is invalid")
        object.__setattr__(self, "claim_id", expected_id)
        object.__setattr__(self, "identity_checksum", checksum)

    def identity_projection(self) -> dict[str, Any]:
        return {
            "schema_revision": self.schema_revision,
            "supporting_refs": list(self.supporting_refs),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.identity_projection(),
            "claim_id": self.claim_id,
            "identity_checksum": self.identity_checksum,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ContextSummaryClaim:
        payload = strict_payload(value, model="ContextSummaryClaim")
        result = cls(
            supporting_refs=tuple(payload.pop("supporting_refs")),
            claim_id=payload.pop("claim_id", None),
            schema_revision=payload.pop(
                "schema_revision",
                CONTEXT_SUMMARY_CLAIM_SCHEMA_REVISION,
            ),
            identity_checksum=payload.pop("identity_checksum", None),
        )
        reject_fields(payload, model="ContextSummaryClaim")
        return result


@dataclass(frozen=True)
class ContextSummaryCandidate:
    summary_artifact_ref: str
    covered_group_ids: tuple[str, ...]
    source_refs: tuple[str, ...]
    claims: tuple[ContextSummaryClaim, ...]
    omitted_topics: tuple[str, ...]
    unresolved_questions: tuple[str, ...]
    tool_outcome_refs: tuple[str, ...]
    loss_risk: ContextLossRisk | str
    worker_id: str
    model_id: str
    worker_revision: str
    model_revision: str
    schema_revision: str = CONTEXT_SUMMARY_CANDIDATE_SCHEMA_REVISION
    candidate_id: str | None = None
    identity_checksum: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "summary_artifact_ref",
            "worker_id",
            "model_id",
            "worker_revision",
            "model_revision",
            "schema_revision",
        ):
            object.__setattr__(
                self,
                field_name,
                required_text(getattr(self, field_name), field=field_name),
            )
        for field_name, required in (
            ("covered_group_ids", True),
            ("source_refs", True),
            ("omitted_topics", False),
            ("unresolved_questions", False),
            ("tool_outcome_refs", False),
        ):
            object.__setattr__(
                self,
                field_name,
                text_tuple(getattr(self, field_name), field=field_name, required=required),
            )
        claims = tuple(self.claims)
        if not claims or not all(isinstance(claim, ContextSummaryClaim) for claim in claims):
            raise HarnessValidationError(
                "claims must contain at least one ContextSummaryClaim"
            )
        object.__setattr__(self, "claims", claims)
        object.__setattr__(self, "loss_risk", ContextLossRisk(self.loss_risk))
        expected_id, checksum = identity("context-summary", self.identity_projection())
        if self.candidate_id is not None and self.candidate_id != expected_id:
            raise HarnessValidationError("candidate_id does not match candidate identity")
        if self.identity_checksum is not None and self.identity_checksum != checksum:
            raise HarnessValidationError("candidate identity checksum is invalid")
        object.__setattr__(self, "candidate_id", expected_id)
        object.__setattr__(self, "identity_checksum", checksum)

    def identity_projection(self) -> dict[str, Any]:
        return {
            "schema_revision": self.schema_revision,
            "summary_artifact_ref": self.summary_artifact_ref,
            "covered_group_ids": list(self.covered_group_ids),
            "source_refs": list(self.source_refs),
            "claims": [claim.identity_projection() for claim in self.claims],
            "omitted_topics": list(self.omitted_topics),
            "unresolved_questions": list(self.unresolved_questions),
            "tool_outcome_refs": list(self.tool_outcome_refs),
            "loss_risk": self.loss_risk.value,
            "worker_id": self.worker_id,
            "model_id": self.model_id,
            "worker_revision": self.worker_revision,
            "model_revision": self.model_revision,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.identity_projection(),
            "claims": [claim.to_dict() for claim in self.claims],
            "candidate_id": self.candidate_id,
            "identity_checksum": self.identity_checksum,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ContextSummaryCandidate:
        payload = strict_payload(value, model="ContextSummaryCandidate")
        raw_claims = payload.pop("claims")
        if not isinstance(raw_claims, (list, tuple)):
            raise HarnessValidationError("ContextSummaryCandidate.claims must be a list")
        result = cls(
            summary_artifact_ref=payload.pop("summary_artifact_ref"),
            covered_group_ids=tuple(payload.pop("covered_group_ids")),
            source_refs=tuple(payload.pop("source_refs")),
            claims=tuple(ContextSummaryClaim.from_dict(claim) for claim in raw_claims),
            omitted_topics=tuple(payload.pop("omitted_topics", ())),
            unresolved_questions=tuple(payload.pop("unresolved_questions", ())),
            tool_outcome_refs=tuple(payload.pop("tool_outcome_refs", ())),
            loss_risk=payload.pop("loss_risk"),
            worker_id=payload.pop("worker_id"),
            model_id=payload.pop("model_id"),
            worker_revision=payload.pop("worker_revision"),
            model_revision=payload.pop("model_revision"),
            schema_revision=payload.pop(
                "schema_revision",
                CONTEXT_SUMMARY_CANDIDATE_SCHEMA_REVISION,
            ),
            candidate_id=payload.pop("candidate_id", None),
            identity_checksum=payload.pop("identity_checksum", None),
        )
        reject_fields(payload, model="ContextSummaryCandidate")
        return result


__all__ = [
    "CONTEXT_SUMMARY_CANDIDATE_SCHEMA_REVISION",
    "CONTEXT_SUMMARY_CLAIM_SCHEMA_REVISION",
    "ContextSummaryCandidate",
    "ContextSummaryClaim",
]
