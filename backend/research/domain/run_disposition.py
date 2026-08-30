from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import Enum
from hashlib import sha256
from typing import Any
from urllib.parse import urlsplit


_CHECKSUM = re.compile(r"^sha256:[0-9a-f]{64}$")
_ACTOR_SCOPE_KEYS = ("tenant_id", "user_id", "memory_namespace")

REQUIRED_ACCEPTED_ARTIFACT_TYPES = frozenset(
    {
        "research-analysis",
        "research-quality-result",
        "harness-trace",
        "harness-transcript",
    }
)


class ResearchRunDisposition(str, Enum):
    """Visibility assigned from deterministic Research acceptance evidence."""

    ACCEPTED = "accepted"
    QUARANTINE = "quarantine"


class ResearchRunDispositionReason(str, Enum):
    ACCEPTED = "accepted"
    TERMINAL_STATUS = "terminal_status_not_succeeded"
    QUALITY_MISSING = "quality_evidence_missing"
    QUALITY_REJECTED = "quality_not_passed"
    IDENTITY_SCOPE_MISSING = "identity_scope_missing"
    IDENTITY_SCOPE_CONFLICT = "identity_scope_conflict"
    SUBJECT_SCOPE_CONFLICT = "subject_scope_conflict"
    ARTIFACT_EVIDENCE_MISSING = "artifact_evidence_missing"
    ARTIFACT_EVIDENCE_CONFLICT = "artifact_evidence_conflict"
    PUBLICATION_AUTHORITY_MISSING = "publication_authority_missing"
    PUBLICATION_AUTHORITY_CONFLICT = "publication_authority_conflict"
    LEGACY_QUARANTINED = "legacy_quarantined"
    RECOVERY_EVIDENCE_MISSING = "recovery_evidence_missing"


@dataclass(frozen=True, slots=True)
class ResearchRunDispositionDecision:
    disposition: ResearchRunDisposition
    reason: ResearchRunDispositionReason
    identity_scope_ref: str | None
    subject_scope_ref: str
    publication_authority_ref: str | None
    artifact_evidence_ref: str | None

    @property
    def accepted(self) -> bool:
        return self.disposition is ResearchRunDisposition.ACCEPTED


def derive_research_run_disposition(
    result: Any,
    *,
    run_id: str,
    paper_id: str,
    identity_scope_ref: str | None = None,
    subject_scope_ref: str | None = None,
    publication_authority_ref: str | None = None,
    artifact_evidence_ref: str | None = None,
    legacy_identity_scope_ref: str | None = None,
    require_publication_authority: bool,
) -> ResearchRunDispositionDecision:
    """Derive canonical visibility from stored evidence without performing I/O."""

    payload = _result_payload(result)
    expected_subject_ref = research_subject_scope_ref(paper_id)
    supplied_subject_ref, subject_invalid = _supplied_checksum(subject_scope_ref)
    if subject_invalid or (
        supplied_subject_ref is not None
        and supplied_subject_ref != expected_subject_ref
    ):
        return _quarantine(
            ResearchRunDispositionReason.SUBJECT_SCOPE_CONFLICT,
            identity_scope_ref=_valid_checksum_or_none(identity_scope_ref),
            subject_scope_ref=expected_subject_ref,
            publication_authority_ref=_valid_checksum_or_none(
                publication_authority_ref
            ),
            artifact_evidence_ref=_valid_checksum_or_none(artifact_evidence_ref),
        )

    derived_scope_ref, scope_reason = _identity_scope_evidence(payload)
    supplied_scope_ref, supplied_scope_invalid = _supplied_checksum(
        identity_scope_ref
    )
    legacy_scope_ref, legacy_scope_invalid = _supplied_checksum(
        legacy_identity_scope_ref
    )
    if supplied_scope_invalid or legacy_scope_invalid:
        scope_reason = ResearchRunDispositionReason.IDENTITY_SCOPE_CONFLICT
    if scope_reason is ResearchRunDispositionReason.IDENTITY_SCOPE_MISSING:
        if legacy_scope_ref is not None:
            derived_scope_ref = legacy_scope_ref
            scope_reason = None
    elif (
        scope_reason is None
        and legacy_scope_ref is not None
        and legacy_scope_ref != derived_scope_ref
    ):
        scope_reason = ResearchRunDispositionReason.IDENTITY_SCOPE_CONFLICT
    if scope_reason is not None:
        return _quarantine(
            scope_reason,
            identity_scope_ref=derived_scope_ref or supplied_scope_ref,
            subject_scope_ref=expected_subject_ref,
            publication_authority_ref=_valid_checksum_or_none(
                publication_authority_ref
            ),
            artifact_evidence_ref=_valid_checksum_or_none(artifact_evidence_ref),
        )
    if supplied_scope_ref is not None and supplied_scope_ref != derived_scope_ref:
        return _quarantine(
            ResearchRunDispositionReason.IDENTITY_SCOPE_CONFLICT,
            identity_scope_ref=derived_scope_ref,
            subject_scope_ref=expected_subject_ref,
            publication_authority_ref=_valid_checksum_or_none(
                publication_authority_ref
            ),
            artifact_evidence_ref=_valid_checksum_or_none(artifact_evidence_ref),
        )

    resolved_artifact_ref, artifact_reason = _artifact_evidence(
        payload,
        run_id=run_id,
        supplied_ref=artifact_evidence_ref,
        require_run_binding=require_publication_authority,
    )
    resolved_authority_ref, authority_conflict = _publication_authority_evidence(
        payload,
        supplied_ref=publication_authority_ref,
    )

    status = payload.get("status")
    if status != "succeeded":
        return _quarantine(
            ResearchRunDispositionReason.TERMINAL_STATUS,
            identity_scope_ref=derived_scope_ref,
            subject_scope_ref=expected_subject_ref,
            publication_authority_ref=resolved_authority_ref,
            artifact_evidence_ref=resolved_artifact_ref,
        )
    quality = payload.get("quality")
    if not isinstance(quality, Mapping) and quality is not None:
        quality = _object_mapping(quality)
    if not isinstance(quality, Mapping) or "passed" not in quality:
        return _quarantine(
            ResearchRunDispositionReason.QUALITY_MISSING,
            identity_scope_ref=derived_scope_ref,
            subject_scope_ref=expected_subject_ref,
            publication_authority_ref=resolved_authority_ref,
            artifact_evidence_ref=resolved_artifact_ref,
        )
    if quality.get("passed") is not True:
        return _quarantine(
            ResearchRunDispositionReason.QUALITY_REJECTED,
            identity_scope_ref=derived_scope_ref,
            subject_scope_ref=expected_subject_ref,
            publication_authority_ref=resolved_authority_ref,
            artifact_evidence_ref=resolved_artifact_ref,
        )
    if derived_scope_ref is None:
        return _quarantine(
            ResearchRunDispositionReason.IDENTITY_SCOPE_MISSING,
            identity_scope_ref=None,
            subject_scope_ref=expected_subject_ref,
            publication_authority_ref=resolved_authority_ref,
            artifact_evidence_ref=resolved_artifact_ref,
        )
    if artifact_reason is not None:
        return _quarantine(
            artifact_reason,
            identity_scope_ref=derived_scope_ref,
            subject_scope_ref=expected_subject_ref,
            publication_authority_ref=resolved_authority_ref,
            artifact_evidence_ref=resolved_artifact_ref,
        )
    if authority_conflict:
        return _quarantine(
            ResearchRunDispositionReason.PUBLICATION_AUTHORITY_CONFLICT,
            identity_scope_ref=derived_scope_ref,
            subject_scope_ref=expected_subject_ref,
            publication_authority_ref=resolved_authority_ref,
            artifact_evidence_ref=resolved_artifact_ref,
        )
    if require_publication_authority and resolved_authority_ref is None:
        return _quarantine(
            ResearchRunDispositionReason.PUBLICATION_AUTHORITY_MISSING,
            identity_scope_ref=derived_scope_ref,
            subject_scope_ref=expected_subject_ref,
            publication_authority_ref=None,
            artifact_evidence_ref=resolved_artifact_ref,
        )
    return ResearchRunDispositionDecision(
        disposition=ResearchRunDisposition.ACCEPTED,
        reason=ResearchRunDispositionReason.ACCEPTED,
        identity_scope_ref=derived_scope_ref,
        subject_scope_ref=expected_subject_ref,
        publication_authority_ref=resolved_authority_ref,
        artifact_evidence_ref=resolved_artifact_ref,
    )


def research_identity_scope_ref(scope: Mapping[str, Any]) -> str:
    return _checksum_for(research_event_tenant_id(scope))


def research_event_tenant_id(scope: Mapping[str, Any]) -> str:
    """Return the opaque canonical tenant key used by durable Harness events.

    The event runtime hashes its tenant id into ``identity_scope_ref``.  Using
    an already-opaque Research scope claim as that tenant id keeps tenant/user
    details out of the event envelope while ensuring the Research disposition,
    Harness activity, and side-effect authorization resolve the same scope ref.
    """

    normalized = _scope_projection(scope)
    if normalized is None:
        raise ValueError("identity scope is incomplete")
    scope_claim_ref = _checksum_for({"identity_scope": normalized})
    return f"research-scope:{scope_claim_ref}"


def research_subject_scope_ref(paper_id: str) -> str:
    if not isinstance(paper_id, str) or not paper_id.strip():
        raise ValueError("paper_id is required")
    return _checksum_for({"paper_id": paper_id})


def disposition_claim_matches(
    decision: ResearchRunDispositionDecision,
    *,
    disposition: ResearchRunDisposition | str | None,
    disposition_reason: str | None,
    identity_scope_ref: str | None,
    subject_scope_ref: str | None,
    publication_authority_ref: str | None,
    artifact_evidence_ref: str | None,
) -> bool:
    """Return whether an explicit persisted/caller claim exactly matches evidence."""

    if disposition is not None:
        try:
            if ResearchRunDisposition(disposition) is not decision.disposition:
                return False
        except (TypeError, ValueError):
            return False
    if disposition_reason is not None and disposition_reason != decision.reason.value:
        return False
    expected = (
        (identity_scope_ref, decision.identity_scope_ref),
        (subject_scope_ref, decision.subject_scope_ref),
        (publication_authority_ref, decision.publication_authority_ref),
        (artifact_evidence_ref, decision.artifact_evidence_ref),
    )
    return all(claimed is None or claimed == derived for claimed, derived in expected)


def apply_research_run_disposition(
    record: Any,
    decision: ResearchRunDispositionDecision,
    *,
    schema_version: str | None = None,
) -> Any:
    """Project a domain decision onto a record-shaped boundary DTO.

    The function intentionally uses a structural record rather than importing
    the run-store port, keeping the domain policy reusable by adapters.
    """

    return replace(
        record,
        disposition=decision.disposition,
        disposition_reason=decision.reason.value,
        identity_scope_ref=decision.identity_scope_ref,
        subject_scope_ref=decision.subject_scope_ref,
        publication_authority_ref=decision.publication_authority_ref,
        artifact_evidence_ref=decision.artifact_evidence_ref,
        schema_version=schema_version
        if schema_version is not None
        else getattr(record, "schema_version", None),
    )


def _identity_scope_evidence(
    payload: Mapping[str, Any],
) -> tuple[str | None, ResearchRunDispositionReason | None]:
    projections: list[dict[str, str]] = []
    explicit = _scope_projection(payload.get("actor_scope"))
    if explicit is not None:
        projections.append(explicit)

    trace = payload.get("trace")
    if isinstance(trace, Mapping):
        trace_scope = _scope_projection(trace.get("metadata"))
        if trace_scope is not None:
            projections.append(trace_scope)
    transcript = payload.get("transcript")
    if isinstance(transcript, Mapping):
        entries = transcript.get("entries")
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, Mapping):
                    projection = _scope_projection(entry.get("metadata"))
                    if projection is not None:
                        projections.append(projection)

    if not projections:
        return None, ResearchRunDispositionReason.IDENTITY_SCOPE_MISSING
    expected = projections[0]
    if any(projection != expected for projection in projections[1:]):
        return None, ResearchRunDispositionReason.IDENTITY_SCOPE_CONFLICT
    return research_identity_scope_ref(expected), None


def _artifact_evidence(
    payload: Mapping[str, Any],
    *,
    run_id: str,
    supplied_ref: str | None,
    require_run_binding: bool,
) -> tuple[str | None, ResearchRunDispositionReason | None]:
    supplied, supplied_invalid = _supplied_checksum(supplied_ref)
    refs = payload.get("artifact_refs")
    if not isinstance(refs, Mapping):
        return None, ResearchRunDispositionReason.ARTIFACT_EVIDENCE_MISSING
    normalized: dict[str, str] = {}
    for key, value in refs.items():
        if not isinstance(key, str) or not key or not isinstance(value, str):
            return None, ResearchRunDispositionReason.ARTIFACT_EVIDENCE_CONFLICT
        try:
            parsed = urlsplit(value)
        except ValueError:
            return None, ResearchRunDispositionReason.ARTIFACT_EVIDENCE_CONFLICT
        if (
            parsed.scheme != "artifact"
            or not parsed.netloc
            or (require_run_binding and parsed.netloc != run_id)
            or parsed.query
            or parsed.fragment
            or not parsed.path.startswith("/")
            or parsed.path == "/"
        ):
            return None, ResearchRunDispositionReason.ARTIFACT_EVIDENCE_CONFLICT
        normalized[key] = value
    if not REQUIRED_ACCEPTED_ARTIFACT_TYPES.issubset(normalized):
        return None, ResearchRunDispositionReason.ARTIFACT_EVIDENCE_MISSING
    if len(set(normalized.values())) != len(normalized):
        return None, ResearchRunDispositionReason.ARTIFACT_EVIDENCE_CONFLICT
    derived = _checksum_for({"artifact_refs": normalized})
    if supplied_invalid or (supplied is not None and supplied != derived):
        return derived, ResearchRunDispositionReason.ARTIFACT_EVIDENCE_CONFLICT
    return derived, None


def _publication_authority_evidence(
    payload: Mapping[str, Any],
    *,
    supplied_ref: str | None,
) -> tuple[str | None, bool]:
    """Resolve publication authority separately from terminal outcome refs.

    A terminal publication produces at least two different checksums: the
    authorization decision and the handler outcome.  The outcome proves that
    the effect was committed, but it is not another publication authority
    claim.  Treating both values as one candidate would quarantine every
    legitimate run because their checksums must differ.
    """

    candidates: list[str] = []
    supplied, supplied_invalid = _supplied_checksum(supplied_ref)
    if supplied is not None:
        candidates.append(supplied)
    diagnostics = payload.get("diagnostics")
    diagnostic_invalid = False
    if isinstance(diagnostics, Mapping):
        for key in (
            "publication_authority_ref",
            "terminal_publication_authority_ref",
        ):
            raw = diagnostics.get(key)
            value, invalid = _supplied_checksum(raw)
            diagnostic_invalid = diagnostic_invalid or invalid
            if value is not None:
                candidates.append(value)
        # The outcome is an independent evidence reference.  Validate its
        # shape when present, but never compare it with the authority ref.
        outcome_ref = diagnostics.get("terminal_side_effect_outcome_ref")
        if outcome_ref is not None:
            _, outcome_invalid = _supplied_checksum(outcome_ref)
            diagnostic_invalid = diagnostic_invalid or outcome_invalid
    unique = set(candidates)
    conflict = supplied_invalid or diagnostic_invalid or len(unique) > 1
    return (candidates[0] if candidates else None), conflict


def _result_payload(result: Any) -> dict[str, Any]:
    if isinstance(result, Mapping):
        return dict(result)
    for name in ("to_persistence_dict", "to_dict"):
        encoder = getattr(result, name, None)
        if callable(encoder):
            value = encoder()
            if isinstance(value, Mapping):
                return dict(value)
    return _object_mapping(result)


def _object_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    names = (
        "run_id",
        "status",
        "quality",
        "artifact_refs",
        "actor_scope",
        "trace",
        "transcript",
        "diagnostics",
    )
    return {name: getattr(value, name) for name in names if hasattr(value, name)}


def _scope_projection(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        to_metadata = getattr(value, "to_metadata", None)
        if callable(to_metadata):
            value = to_metadata()
        else:
            value = {key: getattr(value, key, None) for key in _ACTOR_SCOPE_KEYS}
    if not isinstance(value, Mapping):
        return None
    present = {
        key: str(value.get(key) or "").strip()
        for key in _ACTOR_SCOPE_KEYS
        if str(value.get(key) or "").strip()
    }
    if not present.get("memory_namespace"):
        return None
    return present


def _quarantine(
    reason: ResearchRunDispositionReason,
    *,
    identity_scope_ref: str | None,
    subject_scope_ref: str,
    publication_authority_ref: str | None,
    artifact_evidence_ref: str | None,
) -> ResearchRunDispositionDecision:
    return ResearchRunDispositionDecision(
        disposition=ResearchRunDisposition.QUARANTINE,
        reason=reason,
        identity_scope_ref=identity_scope_ref,
        subject_scope_ref=subject_scope_ref,
        publication_authority_ref=publication_authority_ref,
        artifact_evidence_ref=artifact_evidence_ref,
    )


def _supplied_checksum(value: Any) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    if not isinstance(value, str) or _CHECKSUM.fullmatch(value) is None:
        return None, True
    return value, False


def _valid_checksum_or_none(value: Any) -> str | None:
    checksum, invalid = _supplied_checksum(value)
    return None if invalid else checksum


def _checksum_for(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{sha256(encoded).hexdigest()}"


__all__ = [
    "REQUIRED_ACCEPTED_ARTIFACT_TYPES",
    "ResearchRunDisposition",
    "ResearchRunDispositionDecision",
    "ResearchRunDispositionReason",
    "derive_research_run_disposition",
    "disposition_claim_matches",
    "apply_research_run_disposition",
    "research_event_tenant_id",
    "research_identity_scope_ref",
    "research_subject_scope_ref",
]
