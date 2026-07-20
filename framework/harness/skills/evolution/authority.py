from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from framework.events.canonical import checksum_for
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.side_effects.models import (
    HarnessSideEffectDecision,
    HarnessSideEffectDecisionStatus,
    HarnessSideEffectDisposition,
    HarnessSideEffectHandlerReference,
    HarnessSideEffectIntent,
)
from framework.harness.side_effects.ports import HarnessSideEffectStorePort
from framework.shared.json import to_jsonable

from framework.harness.skills.evolution.models import (
    SkillCandidate,
    SkillEvaluationResult,
    SkillPromotionDecision,
    SkillRelease,
    SkillRollbackPlan,
)


SKILL_RELEASE_EFFECT_KIND = "skill_release"
SKILL_RELEASE_HANDLER = "harness.skill.release@1"
SKILL_RELEASE_AUTHORITY_SCHEMA = "newsroom.skill-release-authority/v1"
SKILL_RELEASE_EVIDENCE_SCHEMA = "newsroom.skill-release-evidence/v1"
_MOVING_VERSIONS = frozenset({"current", "default", "latest", "stable"})


@dataclass(frozen=True, slots=True)
class SkillReleaseAuthorization:
    """Immutable provenance record required before an active skill mutation."""

    candidate_id: str
    candidate_ref: str
    evaluation_ref: str
    promotion_decision_ref: str
    promotion_gate_ref: str
    approval_ref: str
    package_hash: str
    release_id: str
    release_version: str
    rollback_plan_ref: str
    side_effect_intent_ref: str
    side_effect_decision_ref: str
    handler: HarnessSideEffectHandlerReference | str | Mapping[str, Any]
    idempotency_key: str
    skill_name: str
    schema_version: str = SKILL_RELEASE_AUTHORITY_SCHEMA
    checksum: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "candidate_id",
            "release_id",
            "release_version",
            "idempotency_key",
            "skill_name",
            "schema_version",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value or value.strip() != value:
                raise HarnessValidationError(f"{field_name} is required")
        for field_name in (
            "candidate_ref",
            "evaluation_ref",
            "promotion_decision_ref",
            "promotion_gate_ref",
            "approval_ref",
            "package_hash",
            "rollback_plan_ref",
            "side_effect_intent_ref",
            "side_effect_decision_ref",
        ):
            _require_checksum(getattr(self, field_name), field_name)
        if self.release_version.casefold() in _MOVING_VERSIONS:
            raise HarnessValidationError("release_version must be an exact version")
        object.__setattr__(self, "handler", HarnessSideEffectHandlerReference.parse(self.handler))
        expected = checksum_for(self._checksum_payload())
        if self.checksum is not None and self.checksum != expected:
            raise _authority_error(
                "skill_release_authority_checksum_mismatch",
                "skill release authority checksum does not match its canonical payload",
            )
        object.__setattr__(self, "checksum", expected)

    @property
    def authorization_ref(self) -> str:
        assert self.checksum is not None
        return self.checksum

    @property
    def handler_ref(self) -> HarnessSideEffectHandlerReference:
        return self.handler

    def _checksum_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "candidate_ref": self.candidate_ref,
            "evaluation_ref": self.evaluation_ref,
            "promotion_decision_ref": self.promotion_decision_ref,
            "promotion_gate_ref": self.promotion_gate_ref,
            "approval_ref": self.approval_ref,
            "package_hash": self.package_hash,
            "release_id": self.release_id,
            "release_version": self.release_version,
            "rollback_plan_ref": self.rollback_plan_ref,
            "side_effect_intent_ref": self.side_effect_intent_ref,
            "side_effect_decision_ref": self.side_effect_decision_ref,
            "handler": self.handler.to_dict(),
            "idempotency_key": self.idempotency_key,
            "skill_name": self.skill_name,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._checksum_payload(), "checksum": self.checksum}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SkillReleaseAuthorization:
        if not isinstance(value, Mapping):
            raise HarnessValidationError("skill release authority must be an object")
        return cls(
            candidate_id=value.get("candidate_id"),
            candidate_ref=value.get("candidate_ref"),
            evaluation_ref=value.get("evaluation_ref"),
            promotion_decision_ref=value.get("promotion_decision_ref"),
            promotion_gate_ref=value.get("promotion_gate_ref"),
            approval_ref=value.get("approval_ref"),
            package_hash=value.get("package_hash"),
            release_id=value.get("release_id"),
            release_version=value.get("release_version"),
            rollback_plan_ref=value.get("rollback_plan_ref"),
            side_effect_intent_ref=value.get("side_effect_intent_ref"),
            side_effect_decision_ref=value.get("side_effect_decision_ref"),
            handler=value.get("handler"),
            idempotency_key=value.get("idempotency_key"),
            skill_name=value.get("skill_name"),
            schema_version=value.get("schema_version", SKILL_RELEASE_AUTHORITY_SCHEMA),
            checksum=value.get("checksum"),
        )


@dataclass(frozen=True, slots=True)
class ResolvedSkillReleaseAuthorization:
    authorization: SkillReleaseAuthorization
    candidate: SkillCandidate
    evaluation: SkillEvaluationResult
    promotion_decision: SkillPromotionDecision
    release: SkillRelease
    side_effect_intent: HarnessSideEffectIntent
    side_effect_decision: HarnessSideEffectDecision


@runtime_checkable
class SkillReleaseAuthorityResolver(Protocol):
    def resolve(self, authorization_ref: str) -> ResolvedSkillReleaseAuthorization:
        ...


class InMemorySkillReleaseAuthorityResolver:
    """Contract resolver backed by canonical in-memory side-effect decisions.

    This class is deliberately an in-memory contract implementation. A production
    release store must resolve the same references from durable candidate/eval and
    Harness history stores before mutating an active package.
    """

    production_ready = False

    def __init__(
        self,
        side_effect_store: HarnessSideEffectStorePort,
        *,
        handler: HarnessSideEffectHandlerReference | str = SKILL_RELEASE_HANDLER,
    ) -> None:
        self._side_effect_store = side_effect_store
        self._handler = HarnessSideEffectHandlerReference.parse(handler)
        self._records: dict[str, ResolvedSkillReleaseAuthorization] = {}
        self.registration_count = 0

    @property
    def handler(self) -> HarnessSideEffectHandlerReference:
        return self._handler

    def register(
        self,
        *,
        candidate: SkillCandidate,
        evaluation: SkillEvaluationResult,
        promotion_decision: SkillPromotionDecision,
        release: SkillRelease,
        side_effect_intent: HarnessSideEffectIntent,
        side_effect_decision_ref: str,
    ) -> SkillReleaseAuthorization:
        if not isinstance(candidate, SkillCandidate):
            raise TypeError("candidate must be SkillCandidate")
        if not isinstance(evaluation, SkillEvaluationResult):
            raise TypeError("evaluation must be SkillEvaluationResult")
        if not isinstance(promotion_decision, SkillPromotionDecision):
            raise TypeError("promotion_decision must be SkillPromotionDecision")
        if not isinstance(release, SkillRelease):
            raise TypeError("release must be SkillRelease")
        if not isinstance(side_effect_intent, HarnessSideEffectIntent):
            raise TypeError("side_effect_intent must be HarnessSideEffectIntent")
        _require_checksum(side_effect_decision_ref, "side_effect_decision_ref")
        decision = self._side_effect_store.get_decision(side_effect_decision_ref)
        if decision is None:
            raise _authority_error(
                "skill_release_side_effect_decision_missing",
                "skill release side-effect decision is not durably recorded",
                side_effect_decision_ref=side_effect_decision_ref,
            )
        authorization = _build_authorization(
            candidate=candidate,
            evaluation=evaluation,
            promotion_decision=promotion_decision,
            release=release,
            side_effect_intent=side_effect_intent,
            side_effect_decision=decision,
            expected_handler=self._handler,
        )
        record = ResolvedSkillReleaseAuthorization(
            authorization=authorization,
            candidate=candidate,
            evaluation=evaluation,
            promotion_decision=promotion_decision,
            release=release,
            side_effect_intent=side_effect_intent,
            side_effect_decision=decision,
        )
        existing = self._records.get(authorization.authorization_ref)
        if existing is not None:
            if existing != record:
                raise _authority_error(
                    "skill_release_authority_collision",
                    "skill release authority reference is already bound to different evidence",
                    authorization_ref=authorization.authorization_ref,
                )
            return existing.authorization
        self._records[authorization.authorization_ref] = record
        self.registration_count += 1
        return authorization

    def resolve(self, authorization_ref: str) -> ResolvedSkillReleaseAuthorization:
        _require_checksum(authorization_ref, "authorization_ref")
        record = self._records.get(authorization_ref)
        if record is None:
            raise _authority_error(
                "skill_release_authority_missing",
                "skill release authority is not registered",
                authorization_ref=authorization_ref,
            )
        decision = self._side_effect_store.get_decision(record.authorization.side_effect_decision_ref)
        if decision is None:
            raise _authority_error(
                "skill_release_side_effect_decision_missing",
                "skill release side-effect decision is no longer resolvable",
                side_effect_decision_ref=record.authorization.side_effect_decision_ref,
            )
        rebuilt = _build_authorization(
            candidate=record.candidate,
            evaluation=record.evaluation,
            promotion_decision=record.promotion_decision,
            release=record.release,
            side_effect_intent=record.side_effect_intent,
            side_effect_decision=decision,
            expected_handler=self._handler,
        )
        if rebuilt != record.authorization or decision != record.side_effect_decision:
            raise _authority_error(
                "skill_release_authority_evidence_mismatch",
                "skill release authority evidence no longer matches canonical records",
                authorization_ref=authorization_ref,
            )
        return record


def skill_candidate_ref(candidate: SkillCandidate) -> str:
    if not isinstance(candidate, SkillCandidate):
        raise TypeError("candidate must be SkillCandidate")
    payload = candidate.to_dict()
    for key in ("status", "evaluation_results", "promotion_decision", "created_at"):
        payload.pop(key, None)
    return checksum_for(payload)


def skill_evaluation_ref(evaluation: SkillEvaluationResult) -> str:
    if not isinstance(evaluation, SkillEvaluationResult):
        raise TypeError("evaluation must be SkillEvaluationResult")
    return checksum_for(evaluation.to_dict())


def skill_promotion_decision_ref(decision: SkillPromotionDecision) -> str:
    if not isinstance(decision, SkillPromotionDecision):
        raise TypeError("decision must be SkillPromotionDecision")
    payload = decision.to_dict()
    payload.pop("release_authorization_ref", None)
    return checksum_for(payload)


def skill_promotion_gate_ref(decision: SkillPromotionDecision) -> str:
    return checksum_for({"gate_results": to_jsonable(list(decision.gate_results))})


def skill_rollback_plan_ref(plan: SkillRollbackPlan) -> str:
    if not isinstance(plan, SkillRollbackPlan):
        raise TypeError("plan must be SkillRollbackPlan")
    payload = plan.to_dict()
    payload.pop("release_authorization_ref", None)
    payload.pop("side_effect_decision_ref", None)
    return checksum_for(payload)


def skill_package_hash(candidate: SkillCandidate) -> str:
    if not isinstance(candidate, SkillCandidate):
        raise TypeError("candidate must be SkillCandidate")
    manifest = dict(candidate.manifest_snapshot)
    supplied = manifest.get("package_hash")
    snapshot = manifest.get("package_snapshot")
    if supplied is not None:
        _require_checksum(supplied, "package_hash")
        if isinstance(snapshot, Mapping) and checksum_for(snapshot) != supplied:
            raise _authority_error(
                "skill_package_hash_mismatch",
                "candidate package hash does not match its immutable package snapshot",
                candidate_id=candidate.candidate_id,
            )
        return str(supplied)
    if isinstance(snapshot, Mapping):
        return checksum_for(snapshot)
    manifest.pop("package_hash", None)
    manifest.pop("package_snapshot", None)
    return checksum_for(manifest)


def skill_release_evidence_payload(
    *,
    candidate: SkillCandidate,
    evaluation: SkillEvaluationResult,
    promotion_decision: SkillPromotionDecision,
    release: SkillRelease,
    approval_ref: str,
) -> dict[str, Any]:
    return {
        "schema_version": SKILL_RELEASE_EVIDENCE_SCHEMA,
        "candidate_id": candidate.candidate_id,
        "candidate_ref": skill_candidate_ref(candidate),
        "evaluation_ref": skill_evaluation_ref(evaluation),
        "promotion_decision_ref": skill_promotion_decision_ref(promotion_decision),
        "promotion_gate_ref": skill_promotion_gate_ref(promotion_decision),
        "approval_ref": approval_ref,
        "package_hash": skill_package_hash(candidate),
        "release_id": release.release_id,
        "release_version": release.version.version,
        "rollback_plan_ref": skill_rollback_plan_ref(release.rollback_plan),
    }


def _build_authorization(
    *,
    candidate: SkillCandidate,
    evaluation: SkillEvaluationResult,
    promotion_decision: SkillPromotionDecision,
    release: SkillRelease,
    side_effect_intent: HarnessSideEffectIntent,
    side_effect_decision: HarnessSideEffectDecision,
    expected_handler: HarnessSideEffectHandlerReference,
) -> SkillReleaseAuthorization:
    if evaluation.candidate_id != candidate.candidate_id or not evaluation.passed:
        raise _authority_error(
            "skill_release_evaluation_mismatch",
            "skill release requires a passing evaluation for the canonical candidate",
        )
    if evaluation.held_out_score is None or not any(
        result.get("split") == "held_out" for result in evaluation.case_results
    ):
        raise _authority_error(
            "skill_release_held_out_eval_missing",
            "skill release requires held-out evaluation evidence",
        )
    if promotion_decision.candidate_id != candidate.candidate_id or not promotion_decision.is_approved:
        raise _authority_error(
            "skill_release_promotion_not_approved",
            "skill release requires an approved Harness promotion decision",
        )
    if promotion_decision.decided_by != "harness":
        raise _authority_error(
            "skill_release_decision_not_harness_owned",
            "skill release promotion decision is not Harness-owned",
        )
    if not promotion_decision.gate_results or not _all_gate_results_passed(
        promotion_decision.gate_results
    ):
        raise _authority_error(
            "skill_release_promotion_gate_failed",
            "skill release requires passing deterministic promotion gates",
        )
    release_version = release.version.version
    if promotion_decision.required_release_version != release_version:
        raise _authority_error(
            "skill_release_version_mismatch",
            "release version does not match the canonical promotion decision",
        )
    if release.candidate_id != candidate.candidate_id:
        raise _authority_error(
            "skill_release_candidate_mismatch",
            "release candidate does not match canonical candidate",
        )
    package_hash = skill_package_hash(candidate)
    if release.version.package_hash != package_hash:
        raise _authority_error(
            "skill_release_package_hash_mismatch",
            "release package hash does not match canonical candidate package",
        )
    if release.version.skill_name != candidate.base_version.skill_name:
        raise _authority_error(
            "skill_release_skill_mismatch",
            "release skill does not match canonical candidate",
        )
    if release.release_id != f"skill-release://{release.version.skill_name}/{release_version}":
        raise _authority_error(
            "skill_release_id_mismatch",
            "release id is not derived from the canonical skill/version",
        )
    if release.promotion_decision is not None and skill_promotion_decision_ref(release.promotion_decision) != skill_promotion_decision_ref(promotion_decision):
        raise _authority_error(
            "skill_release_decision_mismatch",
            "release promotion decision does not match canonical decision",
        )
    if release.rollback_plan.release_id != release.release_id:
        raise _authority_error(
            "skill_release_rollback_mismatch",
            "rollback plan does not target the canonical release",
        )

    approval_ref = side_effect_decision.approval_evidence_ref
    if approval_ref is None:
        raise _authority_error(
            "skill_release_approval_missing",
            "skill release side-effect decision requires approval policy evidence",
        )
    _require_checksum(approval_ref, "approval_ref")
    if promotion_decision.approval_ref is not None:
        _require_checksum(promotion_decision.approval_ref, "approval_ref")
        if promotion_decision.approval_ref != approval_ref:
            raise _authority_error(
                "skill_release_approval_mismatch",
                "promotion approval does not match side-effect approval evidence",
            )
    if _requires_approval(promotion_decision) and promotion_decision.approval_ref is None:
        raise _authority_error(
            "skill_release_approval_required",
            "high-risk skill release requires approval evidence",
        )

    expected_payload = skill_release_evidence_payload(
        candidate=candidate,
        evaluation=evaluation,
        promotion_decision=promotion_decision,
        release=release,
        approval_ref=approval_ref,
    )
    if side_effect_intent.kind != SKILL_RELEASE_EFFECT_KIND:
        raise _authority_error(
            "skill_release_effect_kind_mismatch",
            "side-effect intent is not a skill release effect",
        )
    if side_effect_intent.handler != expected_handler:
        raise _authority_error(
            "skill_release_handler_mismatch",
            "side-effect intent uses an unapproved skill release handler",
        )
    if to_jsonable(dict(side_effect_intent.payload)) != to_jsonable(expected_payload):
        raise _authority_error(
            "skill_release_evidence_mismatch",
            "side-effect intent does not carry the canonical release evidence refs",
        )
    candidate_ref = expected_payload["candidate_ref"]
    if side_effect_intent.candidate_checksum != candidate_ref:
        raise _authority_error(
            "skill_release_candidate_ref_mismatch",
            "side-effect intent candidate checksum does not match canonical candidate",
        )
    expected_subject_scope = checksum_for({"skill_name": candidate.base_version.skill_name})
    if side_effect_intent.subject_scope_ref != expected_subject_scope:
        raise _authority_error(
            "skill_release_subject_scope_mismatch",
            "skill release subject scope is not bound to the canonical skill",
        )
    if side_effect_decision.checksum is None or side_effect_decision.intent_ref != side_effect_intent.checksum:
        raise _authority_error(
            "skill_release_side_effect_intent_mismatch",
            "side-effect decision is not bound to the canonical intent",
        )
    if (
        side_effect_decision.kind != SKILL_RELEASE_EFFECT_KIND
        or side_effect_decision.handler != expected_handler
        or side_effect_decision.status is not HarnessSideEffectDecisionStatus.AUTHORIZED
        or side_effect_decision.disposition is not HarnessSideEffectDisposition.ACCEPTED
        or side_effect_decision.effect_id != side_effect_intent.effect_id
        or side_effect_decision.run_id != side_effect_intent.run_id
        or side_effect_decision.origin != side_effect_intent.origin
        or side_effect_decision.identity_scope_ref != side_effect_intent.identity_scope_ref
        or side_effect_decision.subject_scope_ref != side_effect_intent.subject_scope_ref
        or side_effect_decision.atomic_group != side_effect_intent.atomic_group
        or side_effect_decision.idempotency_key != side_effect_intent.idempotency_key
        or side_effect_decision.attempt != side_effect_intent.attempt
    ):
        raise _authority_error(
            "skill_release_side_effect_decision_mismatch",
            "side-effect decision does not match canonical release intent",
        )
    promotion_gate_ref = expected_payload["promotion_gate_ref"]
    if promotion_gate_ref not in side_effect_decision.gate_result_refs:
        raise _authority_error(
            "skill_release_gate_evidence_missing",
            "side-effect decision does not reference promotion gate evidence",
        )
    if side_effect_decision.aggregate_verdict_ref is None or side_effect_decision.budget_ref is None:
        raise _authority_error(
            "skill_release_decision_evidence_incomplete",
            "side-effect decision is missing aggregate gate or budget evidence",
        )

    return SkillReleaseAuthorization(
        candidate_id=candidate.candidate_id,
        candidate_ref=candidate_ref,
        evaluation_ref=expected_payload["evaluation_ref"],
        promotion_decision_ref=expected_payload["promotion_decision_ref"],
        promotion_gate_ref=promotion_gate_ref,
        approval_ref=approval_ref,
        package_hash=package_hash,
        release_id=release.release_id,
        release_version=release_version,
        rollback_plan_ref=expected_payload["rollback_plan_ref"],
        side_effect_intent_ref=side_effect_intent.checksum,
        side_effect_decision_ref=side_effect_decision.checksum,
        handler=expected_handler,
        idempotency_key=side_effect_intent.idempotency_key,
        skill_name=candidate.base_version.skill_name,
    )


def _requires_approval(decision: SkillPromotionDecision) -> bool:
    def visit(value: Any) -> bool:
        if isinstance(value, Mapping):
            if value.get("gate") == "skill_allowed_tools":
                details = value.get("details")
                if isinstance(details, Mapping) and details.get("high_risk_tools"):
                    return True
            return any(visit(item) for item in value.values())
        if isinstance(value, (list, tuple)):
            return any(visit(item) for item in value)
        return False

    return visit(decision.gate_results)


def _all_gate_results_passed(results: tuple[dict[str, Any], ...]) -> bool:
    def passed(value: Any) -> bool:
        if not isinstance(value, Mapping) or value.get("passed") is not True:
            return False
        details = value.get("details")
        if not isinstance(details, Mapping):
            return True
        nested = details.get("gate_results")
        if nested is None:
            return True
        if not isinstance(nested, (list, tuple)) or not nested:
            return False
        return all(passed(item) for item in nested)

    return bool(results) and all(passed(result) for result in results)


def _require_checksum(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise _authority_error(
            "invalid_skill_release_ref",
            f"{field_name} must be a sha256 reference",
            field_name=field_name,
        )
    digest = value.removeprefix("sha256:")
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise _authority_error(
            "invalid_skill_release_ref",
            f"{field_name} must be a sha256 reference",
            field_name=field_name,
        )
    return value


def _authority_error(code: str, message: str, **details: Any) -> HarnessValidationError:
    return HarnessValidationError(message, code=code, details={"code": code, **details})


__all__ = [
    "InMemorySkillReleaseAuthorityResolver",
    "ResolvedSkillReleaseAuthorization",
    "SKILL_RELEASE_AUTHORITY_SCHEMA",
    "SKILL_RELEASE_EFFECT_KIND",
    "SKILL_RELEASE_EVIDENCE_SCHEMA",
    "SKILL_RELEASE_HANDLER",
    "SkillReleaseAuthorization",
    "SkillReleaseAuthorityResolver",
    "skill_candidate_ref",
    "skill_evaluation_ref",
    "skill_package_hash",
    "skill_promotion_decision_ref",
    "skill_promotion_gate_ref",
    "skill_release_evidence_payload",
    "skill_rollback_plan_ref",
]
