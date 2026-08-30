from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from backend.research.domain.run_disposition import (
    REQUIRED_ACCEPTED_ARTIFACT_TYPES,
    ResearchRunDispositionDecision,
    apply_research_run_disposition,
    derive_research_run_disposition,
    disposition_claim_matches,
    research_identity_scope_ref,
    research_subject_scope_ref,
)
from backend.research.ports.run_store import (
    ResearchRunDisposition,
    ResearchRunRecord,
    ResearchRunStore,
    ResearchRunStoreReason,
    ResearchRunStoreValidationError,
)

if TYPE_CHECKING:
    from backend.research.application.single_paper_runtime import AnalyzePaperRequest


def classify_research_run_record(
    record: ResearchRunRecord,
    *,
    require_publication_authority: bool | None,
    schema_version: str | None = None,
    legacy_identity_scope_ref: str | None = None,
) -> ResearchRunRecord:
    """Attach a deterministic domain decision to a port record.

    The application boundary owns conversion from the domain decision to the
    storage DTO. Adapters use the domain policy directly and therefore never
    need to import this application module.
    """

    if not isinstance(record, ResearchRunRecord):
        raise ResearchRunStoreValidationError(ResearchRunStoreReason.INVALID_RECORD)
    effective_legacy_scope = legacy_identity_scope_ref
    if effective_legacy_scope is None and (
        record.schema_version is None
        or str(record.schema_version).endswith(".v1")
    ):
        effective_legacy_scope = record.identity_scope_ref
    policies: tuple[bool, ...] = (
        (False, True)
        if require_publication_authority is None and record.disposition is not None
        else (False,)
        if require_publication_authority is None
        else (require_publication_authority,)
    )
    selected: ResearchRunDispositionDecision | None = None
    for policy in policies:
        candidate = derive_research_run_disposition(
            record.result,
            run_id=record.run_id,
            paper_id=record.paper_id,
            identity_scope_ref=record.identity_scope_ref,
            subject_scope_ref=record.subject_scope_ref,
            publication_authority_ref=record.publication_authority_ref,
            artifact_evidence_ref=record.artifact_evidence_ref,
            legacy_identity_scope_ref=effective_legacy_scope,
            require_publication_authority=policy,
        )
        if disposition_claim_matches(
            candidate,
            disposition=record.disposition,
            disposition_reason=record.disposition_reason,
            identity_scope_ref=record.identity_scope_ref,
            subject_scope_ref=record.subject_scope_ref,
            publication_authority_ref=record.publication_authority_ref,
            artifact_evidence_ref=record.artifact_evidence_ref,
        ):
            selected = candidate
            break
    if selected is None:
        raise ResearchRunStoreValidationError(ResearchRunStoreReason.INVALID_RECORD)
    return apply_research_run_disposition(
        record,
        selected,
        schema_version=schema_version or record.schema_version,
    )


@runtime_checkable
class ResearchRunRecoverySource(Protocol):
    """Read-only durable evidence source; it cannot execute workers or effects."""

    def list_pending_run_ids(self, *, limit: int) -> tuple[str, ...]: ...

    def load_recovery_record(self, run_id: str) -> ResearchRunRecord | None: ...


@runtime_checkable
class ResearchRunFailureRecoverySource(Protocol):
    """Rebuild one raised run from durable history without resuming execution."""

    def load_failure_record(
        self,
        request: "AnalyzePaperRequest",
    ) -> ResearchRunRecord | None: ...


class ResearchRunDispositionReconciler:
    """Bounded, idempotent recovery from durable read-only evidence."""

    def __init__(
        self,
        *,
        run_store: ResearchRunStore,
        recovery_source: ResearchRunRecoverySource,
        max_runs: int = 100,
    ) -> None:
        if not isinstance(run_store, ResearchRunStore):
            raise TypeError("run_store must implement ResearchRunStore")
        if not isinstance(recovery_source, ResearchRunRecoverySource):
            raise TypeError("recovery_source must implement ResearchRunRecoverySource")
        if isinstance(max_runs, bool) or not isinstance(max_runs, int) or max_runs < 1:
            raise ValueError("max_runs must be a positive integer")
        self._run_store = run_store
        self._recovery_source = recovery_source
        self._max_runs = max_runs

    def reconcile_pending(self) -> tuple[ResearchRunRecord, ...]:
        run_ids = self._recovery_source.list_pending_run_ids(limit=self._max_runs)
        if not isinstance(run_ids, (tuple, list)):
            raise ValueError("recovery source returned an invalid bounded run list")
        if len(run_ids) > self._max_runs or len(set(run_ids)) != len(run_ids):
            raise ValueError("recovery source returned an invalid bounded run list")
        if any(not isinstance(run_id, str) or not run_id.strip() for run_id in run_ids):
            raise ValueError("recovery source returned an invalid bounded run list")
        recovered: list[ResearchRunRecord] = []
        for run_id in run_ids:
            record = self.reconcile_run(run_id)
            if record is not None:
                recovered.append(record)
        return tuple(recovered)

    def reconcile_run(
        self,
        run_id: str,
        *,
        expected_paper_id: str | None = None,
        identity_scope_ref: str | None = None,
    ) -> ResearchRunRecord | None:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id is required")
        existing = self._run_store.get_by_run_id(run_id)
        if existing is not None:
            if existing.run_id != run_id:
                raise ValueError("run store returned another run")
            if expected_paper_id is not None and existing.paper_id != expected_paper_id:
                raise ValueError("run store returned another paper")
            if identity_scope_ref is not None and (
                existing.identity_scope_ref != identity_scope_ref
            ):
                raise ValueError("run store returned another identity scope")
            return existing

        candidate = self._recovery_source.load_recovery_record(run_id)
        return self._commit_candidate(
            candidate,
            run_id=run_id,
            expected_paper_id=expected_paper_id,
            identity_scope_ref=identity_scope_ref,
        )

    def reconcile_failed_run(
        self,
        request: "AnalyzePaperRequest",
        *,
        identity_scope_ref: str,
    ) -> ResearchRunRecord | None:
        """Commit a scoped quarantine projection after a raised runtime call."""

        run_id = getattr(request, "run_id", None)
        paper_id = getattr(request, "paper_id", None)
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("request run_id is required")
        if not isinstance(paper_id, str) or not paper_id.strip():
            raise ValueError("request paper_id is required")
        if not isinstance(identity_scope_ref, str) or not identity_scope_ref.strip():
            raise ValueError("identity_scope_ref must be a string")

        existing = self._run_store.get_by_run_id(run_id)
        if existing is not None:
            return self._validate_existing(
                existing,
                run_id=run_id,
                expected_paper_id=paper_id,
                identity_scope_ref=identity_scope_ref,
            )

        if isinstance(self._recovery_source, ResearchRunFailureRecoverySource):
            candidate = self._recovery_source.load_failure_record(request)
        else:
            candidate = self._recovery_source.load_recovery_record(run_id)
        return self._commit_candidate(
            candidate,
            run_id=run_id,
            expected_paper_id=paper_id,
            identity_scope_ref=identity_scope_ref,
        )

    def _commit_candidate(
        self,
        candidate: ResearchRunRecord | None,
        *,
        run_id: str,
        expected_paper_id: str | None,
        identity_scope_ref: str | None,
    ) -> ResearchRunRecord | None:
        if candidate is None:
            return None
        if candidate.run_id != run_id:
            raise ValueError("recovery source returned another run")
        if expected_paper_id is not None and candidate.paper_id != expected_paper_id:
            raise ValueError("recovery source returned another paper")
        if identity_scope_ref is not None and not isinstance(identity_scope_ref, str):
            raise ValueError("identity_scope_ref must be a string")
        is_v2 = (
            candidate.schema_version is not None
            and str(candidate.schema_version).endswith(".v2")
        )
        if (
            is_v2
            and identity_scope_ref is not None
            and candidate.identity_scope_ref != identity_scope_ref
        ):
            raise ValueError("recovery source returned another identity scope")

        # A supplied scope is fallback evidence only for legacy records. For a
        # v2 record it is an independent claim and the domain classifier checks
        # that it matches the persisted scope and the result metadata.
        legacy_scope = (
            identity_scope_ref
            if candidate.schema_version is None
            or str(candidate.schema_version).endswith(".v1")
            else None
        )
        classified = classify_research_run_record(
            candidate,
            require_publication_authority=(
                is_v2
            ),
            schema_version=candidate.schema_version,
            legacy_identity_scope_ref=legacy_scope,
        )
        self._run_store.save(classified)
        return self._run_store.get_by_run_id(run_id)

    @staticmethod
    def _validate_existing(
        existing: ResearchRunRecord,
        *,
        run_id: str,
        expected_paper_id: str | None,
        identity_scope_ref: str | None,
    ) -> ResearchRunRecord:
        if existing.run_id != run_id:
            raise ValueError("run store returned another run")
        if expected_paper_id is not None and existing.paper_id != expected_paper_id:
            raise ValueError("run store returned another paper")
        if (
            identity_scope_ref is not None
            and existing.identity_scope_ref != identity_scope_ref
        ):
            raise ValueError("run store returned another identity scope")
        return existing


__all__ = [
    "REQUIRED_ACCEPTED_ARTIFACT_TYPES",
    "ResearchRunDisposition",
    "ResearchRunDispositionDecision",
    "ResearchRunDispositionReconciler",
    "ResearchRunFailureRecoverySource",
    "ResearchRunRecoverySource",
    "classify_research_run_record",
    "derive_research_run_disposition",
    "disposition_claim_matches",
    "research_identity_scope_ref",
    "research_subject_scope_ref",
]
