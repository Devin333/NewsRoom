from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Literal, Mapping


ProviderReleaseStatus = Literal["held", "approved", "revoked"]
ProviderRolloutState = Literal["disabled", "shadow", "enabled"]
ProviderReleaseEvidenceKind = Literal["recorded_transport", "live_provider"]
ProviderRollbackAction = Literal[
    "json_object_local_gate",
    "previous_capability",
    "alternate_deployment",
    "reject",
]

_RELEASE_STATUSES = frozenset({"held", "approved", "revoked"})
_ROLLOUT_STATES = frozenset({"disabled", "shadow", "enabled"})
_EVIDENCE_KINDS = frozenset({"recorded_transport", "live_provider"})
_ROLLBACK_ACTIONS = frozenset(
    {
        "json_object_local_gate",
        "previous_capability",
        "alternate_deployment",
        "reject",
    }
)
_PROVIDER_ENFORCEMENT_MODES = frozenset({"native_strict", "constrained"})
_RELEASE_KEYS = frozenset(
    {
        "schema_version",
        "release_id",
        "provider",
        "deployment",
        "capability_revision",
        "approved_modes",
        "status",
        "rollout_state",
        "graph_scopes",
        "corpus_revision",
        "corpus_digest",
        "observation_revision",
        "observation_digest",
        "baseline_digest",
        "evaluation_report_digest",
        "evaluation_passed",
        "evidence_kind",
        "evidence_refs",
        "decided_by",
        "approved_by",
        "approved_at",
        "owner",
        "rollout_revision",
        "rollback",
        "reason",
        "record_digest",
    }
)
_ROLLBACK_KEYS = frozenset(
    {
        "action",
        "target_capability_revision",
        "target_deployment",
        "triggers",
    }
)


class ProviderStructuredOutputReleaseError(ValueError):
    """Raised when release evidence is malformed or does not authorize use."""


@dataclass(frozen=True)
class ProviderStructuredOutputRollback:
    action: ProviderRollbackAction
    triggers: tuple[str, ...]
    target_capability_revision: str | None = None
    target_deployment: str | None = None

    def __post_init__(self) -> None:
        if self.action not in _ROLLBACK_ACTIONS:
            raise ProviderStructuredOutputReleaseError(
                "unsupported structured-output rollback action"
            )
        triggers = _required_text_tuple(self.triggers, field_name="rollback.triggers")
        target_revision = _optional_text(self.target_capability_revision)
        target_deployment = _optional_text(self.target_deployment)
        if self.action == "previous_capability" and target_revision is None:
            raise ProviderStructuredOutputReleaseError(
                "previous_capability rollback requires target_capability_revision"
            )
        if self.action == "alternate_deployment" and target_deployment is None:
            raise ProviderStructuredOutputReleaseError(
                "alternate_deployment rollback requires target_deployment"
            )
        object.__setattr__(self, "triggers", triggers)
        object.__setattr__(self, "target_capability_revision", target_revision)
        object.__setattr__(self, "target_deployment", target_deployment)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "target_capability_revision": self.target_capability_revision,
            "target_deployment": self.target_deployment,
            "triggers": list(self.triggers),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ProviderStructuredOutputRollback:
        unknown = sorted(set(payload) - _ROLLBACK_KEYS)
        if unknown:
            raise ProviderStructuredOutputReleaseError(
                "rollback contains unsupported fields: " + ", ".join(unknown)
            )
        return cls(
            action=_required_text(payload.get("action"), field_name="rollback.action"),  # type: ignore[arg-type]
            target_capability_revision=_optional_text(
                payload.get("target_capability_revision")
            ),
            target_deployment=_optional_text(payload.get("target_deployment")),
            triggers=_text_tuple(payload.get("triggers"), field_name="rollback.triggers"),
        )


@dataclass(frozen=True)
class ProviderStructuredOutputRelease:
    release_id: str
    provider: str
    deployment: str
    capability_revision: str
    approved_modes: frozenset[str]
    status: ProviderReleaseStatus
    rollout_state: ProviderRolloutState
    graph_scopes: tuple[str, ...]
    rollout_revision: str
    rollback: ProviderStructuredOutputRollback
    schema_version: str = "provider-structured-output-release.v2"
    corpus_revision: str | None = None
    corpus_digest: str | None = None
    observation_revision: str | None = None
    observation_digest: str | None = None
    baseline_digest: str | None = None
    evaluation_report_digest: str | None = None
    evaluation_passed: bool = False
    evidence_kind: ProviderReleaseEvidenceKind | None = None
    evidence_refs: tuple[str, ...] = ()
    decided_by: str = "harness"
    approved_by: str | None = None
    approved_at: str | None = None
    owner: str = "llm-platform"
    reason: str | None = None
    record_digest: str | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        for field_name in (
            "schema_version",
            "release_id",
            "provider",
            "deployment",
            "capability_revision",
            "rollout_revision",
            "owner",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        if self.schema_version != "provider-structured-output-release.v2":
            raise ProviderStructuredOutputReleaseError(
                "unsupported provider structured-output release schema_version"
            )
        if self.status not in _RELEASE_STATUSES:
            raise ProviderStructuredOutputReleaseError("unsupported release status")
        if self.rollout_state not in _ROLLOUT_STATES:
            raise ProviderStructuredOutputReleaseError("unsupported rollout state")
        modes = frozenset(
            _required_text(mode, field_name="approved mode")
            for mode in self.approved_modes
        )
        if not modes or modes - _PROVIDER_ENFORCEMENT_MODES:
            raise ProviderStructuredOutputReleaseError(
                "approved_modes must contain native_strict or constrained"
            )
        scopes = _required_text_tuple(
            self.graph_scopes, field_name="graph_scopes"
        )
        if not isinstance(self.evaluation_passed, bool):
            raise ProviderStructuredOutputReleaseError(
                "evaluation_passed must be a boolean"
            )
        evidence_kind = _optional_text(self.evidence_kind)
        if evidence_kind is not None and evidence_kind not in _EVIDENCE_KINDS:
            raise ProviderStructuredOutputReleaseError("unsupported evidence_kind")
        evidence_refs = _text_tuple(
            self.evidence_refs, field_name="evidence_refs", allow_empty=True
        )
        decided_by = _required_text(self.decided_by, field_name="decided_by")
        if decided_by != "harness":
            raise ProviderStructuredOutputReleaseError(
                "provider release decisions must be decided_by='harness'"
            )
        optional_text_fields = (
            "corpus_revision",
            "observation_revision",
            "approved_by",
            "approved_at",
            "reason",
        )
        for field_name in optional_text_fields:
            object.__setattr__(
                self, field_name, _optional_text(getattr(self, field_name))
            )
        digest_fields = (
            "corpus_digest",
            "observation_digest",
            "baseline_digest",
            "evaluation_report_digest",
        )
        for field_name in digest_fields:
            value = _optional_digest(getattr(self, field_name), field_name=field_name)
            object.__setattr__(self, field_name, value)

        if self.rollout_state == "enabled" or self.status == "approved":
            missing = [
                field_name
                for field_name in (
                    "corpus_revision",
                    "corpus_digest",
                    "observation_revision",
                    "observation_digest",
                    "baseline_digest",
                    "evaluation_report_digest",
                    "evidence_kind",
                    "approved_by",
                    "approved_at",
                )
                if getattr(self, field_name) is None
            ]
            if missing or not self.evaluation_passed or not evidence_refs:
                raise ProviderStructuredOutputReleaseError(
                    "approved or enabled release requires passed versioned evaluation evidence"
                )
        if self.rollout_state == "enabled" and self.status != "approved":
            raise ProviderStructuredOutputReleaseError(
                "enabled rollout requires approved release status"
            )

        object.__setattr__(self, "approved_modes", modes)
        object.__setattr__(self, "graph_scopes", scopes)
        object.__setattr__(self, "evidence_kind", evidence_kind)
        object.__setattr__(self, "evidence_refs", evidence_refs)
        object.__setattr__(self, "decided_by", decided_by)
        if not isinstance(self.rollback, ProviderStructuredOutputRollback):
            raise ProviderStructuredOutputReleaseError(
                "rollback must be ProviderStructuredOutputRollback"
            )
        expected_digest = self.digest
        declared_digest = _optional_digest(
            self.record_digest, field_name="record_digest"
        )
        if declared_digest is not None and declared_digest != expected_digest:
            raise ProviderStructuredOutputReleaseError(
                "provider release record_digest does not match record content"
            )
        object.__setattr__(self, "record_digest", expected_digest)

    @property
    def digest(self) -> str:
        return "sha256:" + sha256(_canonical_json_bytes(self.to_dict(include_digest=False))).hexdigest()

    @property
    def is_enabled(self) -> bool:
        return (
            self.status == "approved"
            and self.rollout_state == "enabled"
            and self.evaluation_passed
        )

    def authorization_issues(
        self,
        *,
        provider: str,
        deployment: str,
        capability_revision: str,
        mode: str,
        graph_scope: str,
    ) -> tuple[str, ...]:
        issues: list[str] = []
        if self.provider != provider or self.deployment != deployment:
            issues.append("provider_release_identity_mismatch")
        if self.capability_revision != capability_revision:
            issues.append("provider_release_capability_revision_mismatch")
        if mode not in self.approved_modes:
            issues.append("provider_release_mode_unapproved")
        if "*" not in self.graph_scopes and graph_scope not in self.graph_scopes:
            issues.append("provider_release_scope_ineligible")
        if self.status != "approved":
            issues.append("provider_release_not_approved")
        if self.rollout_state != "enabled":
            issues.append(
                "provider_release_shadow_only"
                if self.rollout_state == "shadow"
                else "provider_release_disabled"
            )
        if not self.evaluation_passed:
            issues.append("provider_release_evaluation_failed")
        return tuple(issues)

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "release_id": self.release_id,
            "provider": self.provider,
            "deployment": self.deployment,
            "capability_revision": self.capability_revision,
            "approved_modes": sorted(self.approved_modes),
            "status": self.status,
            "rollout_state": self.rollout_state,
            "graph_scopes": list(self.graph_scopes),
            "corpus_revision": self.corpus_revision,
            "corpus_digest": self.corpus_digest,
            "observation_revision": self.observation_revision,
            "observation_digest": self.observation_digest,
            "baseline_digest": self.baseline_digest,
            "evaluation_report_digest": self.evaluation_report_digest,
            "evaluation_passed": self.evaluation_passed,
            "evidence_kind": self.evidence_kind,
            "evidence_refs": list(self.evidence_refs),
            "decided_by": self.decided_by,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "owner": self.owner,
            "rollout_revision": self.rollout_revision,
            "rollback": self.rollback.to_dict(),
            "reason": self.reason,
        }
        if include_digest:
            payload["record_digest"] = self.record_digest or self.digest
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ProviderStructuredOutputRelease:
        unknown = sorted(set(payload) - _RELEASE_KEYS)
        if unknown:
            raise ProviderStructuredOutputReleaseError(
                "provider release contains unsupported fields: " + ", ".join(unknown)
            )
        rollback = payload.get("rollback")
        if not isinstance(rollback, Mapping):
            raise ProviderStructuredOutputReleaseError("release rollback must be an object")
        return cls(
            schema_version=_required_text(
                payload.get("schema_version"), field_name="schema_version"
            ),
            release_id=_required_text(payload.get("release_id"), field_name="release_id"),
            provider=_required_text(payload.get("provider"), field_name="provider"),
            deployment=_required_text(payload.get("deployment"), field_name="deployment"),
            capability_revision=_required_text(
                payload.get("capability_revision"), field_name="capability_revision"
            ),
            approved_modes=frozenset(
                _text_tuple(payload.get("approved_modes"), field_name="approved_modes")
            ),
            status=_required_text(payload.get("status"), field_name="status"),  # type: ignore[arg-type]
            rollout_state=_required_text(
                payload.get("rollout_state"), field_name="rollout_state"
            ),  # type: ignore[arg-type]
            graph_scopes=_text_tuple(
                payload.get("graph_scopes"), field_name="graph_scopes"
            ),
            corpus_revision=_optional_text(payload.get("corpus_revision")),
            corpus_digest=payload.get("corpus_digest"),
            observation_revision=_optional_text(payload.get("observation_revision")),
            observation_digest=payload.get("observation_digest"),
            baseline_digest=payload.get("baseline_digest"),
            evaluation_report_digest=payload.get("evaluation_report_digest"),
            evaluation_passed=_strict_bool(
                payload.get("evaluation_passed", False), field_name="evaluation_passed"
            ),
            evidence_kind=_optional_text(payload.get("evidence_kind")),  # type: ignore[arg-type]
            evidence_refs=_text_tuple(
                payload.get("evidence_refs"),
                field_name="evidence_refs",
                allow_empty=True,
            ),
            decided_by=_required_text(
                payload.get("decided_by"), field_name="decided_by"
            ),
            approved_by=_optional_text(payload.get("approved_by")),
            approved_at=_optional_text(payload.get("approved_at")),
            owner=_required_text(payload.get("owner"), field_name="owner"),
            rollout_revision=_required_text(
                payload.get("rollout_revision"), field_name="rollout_revision"
            ),
            rollback=ProviderStructuredOutputRollback.from_dict(rollback),
            reason=_optional_text(payload.get("reason")),
            record_digest=payload.get("record_digest"),
        )


def provider_release_records_from_payload(
    value: Any,
) -> dict[str, ProviderStructuredOutputRelease]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ProviderStructuredOutputReleaseError(
            "structured_output_releases must be an object"
        )
    records: dict[str, ProviderStructuredOutputRelease] = {}
    for key, raw_record in value.items():
        release_id = _required_text(key, field_name="structured_output_releases key")
        if not isinstance(raw_record, Mapping):
            raise ProviderStructuredOutputReleaseError(
                f"structured_output_releases.{release_id} must be an object"
            )
        record = ProviderStructuredOutputRelease.from_dict(raw_record)
        if record.release_id != release_id:
            raise ProviderStructuredOutputReleaseError(
                f"structured_output_releases.{release_id} release_id does not match key"
            )
        records[release_id] = record
    return records


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _required_text(value: Any, *, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ProviderStructuredOutputReleaseError(
            f"{field_name} must be a non-empty string"
        )
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _text_tuple(
    value: Any,
    *,
    field_name: str,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        raise ProviderStructuredOutputReleaseError(f"{field_name} must be a list")
    result = tuple(
        _required_text(item, field_name=field_name)
        for item in value
    )
    if not result and not allow_empty:
        raise ProviderStructuredOutputReleaseError(f"{field_name} must not be empty")
    if len(set(result)) != len(result):
        raise ProviderStructuredOutputReleaseError(
            f"{field_name} must not contain duplicates"
        )
    return result


def _required_text_tuple(value: Any, *, field_name: str) -> tuple[str, ...]:
    return _text_tuple(value, field_name=field_name)


def _optional_digest(value: Any, *, field_name: str) -> str | None:
    text = _optional_text(value)
    if text is None:
        return None
    if len(text) != 71 or not text.startswith("sha256:"):
        raise ProviderStructuredOutputReleaseError(
            f"{field_name} must be a sha256 digest"
        )
    try:
        int(text[7:], 16)
    except ValueError as exc:
        raise ProviderStructuredOutputReleaseError(
            f"{field_name} must be a sha256 digest"
        ) from exc
    return text.casefold()


def _strict_bool(value: Any, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ProviderStructuredOutputReleaseError(
            f"{field_name} must be a boolean"
        )
    return value


__all__ = [
    "ProviderReleaseEvidenceKind",
    "ProviderReleaseStatus",
    "ProviderRollbackAction",
    "ProviderRolloutState",
    "ProviderStructuredOutputRelease",
    "ProviderStructuredOutputReleaseError",
    "ProviderStructuredOutputRollback",
    "provider_release_records_from_payload",
]
