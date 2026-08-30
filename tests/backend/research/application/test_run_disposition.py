from __future__ import annotations

from dataclasses import replace

import pytest

from framework.events.canonical import checksum_for

from backend.research.application.run_disposition import (
    ResearchRunDispositionReconciler,
    classify_research_run_record,
    derive_research_run_disposition,
    research_identity_scope_ref,
)
from backend.research.domain import research_event_tenant_id
from backend.research.ports.run_store import (
    ResearchRunDisposition,
    ResearchRunDispositionReason,
    ResearchRunRecord,
)
from interfaces.services.research_service import InMemoryResearchRunStore


def _result(
    run_id: str = "run-1",
    paper_id: str = "paper-1",
    *,
    status: str = "succeeded",
    quality_passed: bool | None = True,
    scope: dict[str, str] | None = None,
    publication_authority_ref: str | None = None,
) -> dict:
    actor_scope = scope or {"memory_namespace": "research.public"}
    diagnostics = {}
    if publication_authority_ref is not None:
        diagnostics["publication_authority_ref"] = publication_authority_ref
    quality = None if quality_passed is None else {
        "target_id": paper_id,
        "passed": quality_passed,
    }
    return {
        "run_id": run_id,
        "status": status,
        "analysis": {"paper_id": paper_id},
        "quality": quality,
        "artifact_refs": {
            "research-analysis": f"artifact://{run_id}/research-analysis",
            "research-quality-result": f"artifact://{run_id}/research-quality-result",
            "harness-trace": f"artifact://{run_id}/harness-trace",
            "harness-transcript": f"artifact://{run_id}/harness-transcript",
        },
        "actor_scope": dict(actor_scope),
        "trace": {"run_id": run_id, "metadata": dict(actor_scope)},
        "transcript": {"run_id": run_id, "entries": []},
        "diagnostics": diagnostics,
    }


def _checksum(seed: str) -> str:
    return "sha256:" + seed * 64


def test_event_tenant_key_and_research_scope_ref_share_one_identity() -> None:
    scope = {
        "tenant_id": "tenant-a",
        "user_id": "user-a",
        "memory_namespace": "research:tenant:tenant-a:user:user-a",
    }

    tenant_id = research_event_tenant_id(scope)

    assert research_identity_scope_ref(scope) == checksum_for(tenant_id)
    assert "tenant-a" not in tenant_id
    assert "user-a" not in tenant_id


def test_disposition_is_fail_closed_from_terminal_quality_scope_and_authority() -> None:
    accepted_v1 = derive_research_run_disposition(
        _result(),
        run_id="run-1",
        paper_id="paper-1",
        require_publication_authority=False,
    )
    assert accepted_v1.disposition is ResearchRunDisposition.ACCEPTED
    assert accepted_v1.reason is ResearchRunDispositionReason.ACCEPTED
    assert accepted_v1.identity_scope_ref == research_identity_scope_ref(
        {"memory_namespace": "research.public"}
    )

    for payload, reason in (
        (_result(status="halted"), ResearchRunDispositionReason.TERMINAL_STATUS),
        (_result(quality_passed=None), ResearchRunDispositionReason.QUALITY_MISSING),
        (_result(quality_passed=False), ResearchRunDispositionReason.QUALITY_REJECTED),
    ):
        decision = derive_research_run_disposition(
            payload,
            run_id="run-1",
            paper_id="paper-1",
            require_publication_authority=False,
        )
        assert decision.disposition is ResearchRunDisposition.QUARANTINE
        assert decision.reason is reason

    missing_authority = derive_research_run_disposition(
        _result(),
        run_id="run-1",
        paper_id="paper-1",
        require_publication_authority=True,
    )
    assert missing_authority.reason is ResearchRunDispositionReason.PUBLICATION_AUTHORITY_MISSING

    accepted_v2 = derive_research_run_disposition(
        _result(publication_authority_ref=_checksum("a")),
        run_id="run-1",
        paper_id="paper-1",
        require_publication_authority=True,
    )
    assert accepted_v2.disposition is ResearchRunDisposition.ACCEPTED


def test_terminal_outcome_ref_is_independent_from_publication_authority() -> None:
    payload = _result(publication_authority_ref=_checksum("a"))
    payload["diagnostics"]["terminal_side_effect_outcome_ref"] = _checksum("b")

    decision = derive_research_run_disposition(
        payload,
        run_id="run-1",
        paper_id="paper-1",
        require_publication_authority=True,
    )

    assert decision.disposition is ResearchRunDisposition.ACCEPTED
    assert decision.publication_authority_ref == _checksum("a")


def test_malformed_terminal_outcome_ref_is_quarantined() -> None:
    payload = _result(publication_authority_ref=_checksum("a"))
    payload["diagnostics"]["terminal_side_effect_outcome_ref"] = "outcome-not-a-checksum"

    decision = derive_research_run_disposition(
        payload,
        run_id="run-1",
        paper_id="paper-1",
        require_publication_authority=True,
    )

    assert decision.disposition is ResearchRunDisposition.QUARANTINE
    assert decision.reason is ResearchRunDispositionReason.PUBLICATION_AUTHORITY_CONFLICT


def test_scope_conflicts_and_incomplete_artifacts_are_quarantined() -> None:
    conflict = _result()
    conflict["trace"]["metadata"] = {
        "tenant_id": "tenant-a",
        "memory_namespace": "research:tenant:tenant-a:public",
    }
    decision = derive_research_run_disposition(
        conflict,
        run_id="run-1",
        paper_id="paper-1",
        require_publication_authority=False,
    )
    assert decision.reason is ResearchRunDispositionReason.IDENTITY_SCOPE_CONFLICT

    incomplete = _result()
    incomplete["artifact_refs"].pop("harness-transcript")
    decision = derive_research_run_disposition(
        incomplete,
        run_id="run-1",
        paper_id="paper-1",
        require_publication_authority=False,
    )
    assert decision.reason is ResearchRunDispositionReason.ARTIFACT_EVIDENCE_MISSING


class _RecoverySource:
    def __init__(self, record: ResearchRunRecord) -> None:
        self.record = record
        self.list_calls = 0
        self.load_calls = 0

    def list_pending_run_ids(self, *, limit: int) -> tuple[str, ...]:
        self.list_calls += 1
        return (self.record.run_id,)[:limit]

    def load_recovery_record(self, run_id: str) -> ResearchRunRecord | None:
        self.load_calls += 1
        return self.record if run_id == self.record.run_id else None


def test_reconciler_is_bounded_idempotent_and_uses_only_read_evidence() -> None:
    authority_ref = _checksum("b")
    candidate = ResearchRunRecord(
        run_id="run-recover",
        paper_id="paper-1",
        result=_result(
            run_id="run-recover",
            publication_authority_ref=authority_ref,
        ),
        publication_authority_ref=authority_ref,
    )
    store = InMemoryResearchRunStore()
    source = _RecoverySource(candidate)
    reconciler = ResearchRunDispositionReconciler(
        run_store=store,
        recovery_source=source,
        max_runs=1,
    )

    recovered = reconciler.reconcile_pending()
    assert len(recovered) == 1
    assert recovered[0].accepted
    assert source.list_calls == 1
    assert source.load_calls == 1

    assert reconciler.reconcile_run("run-recover") == recovered[0]
    assert source.load_calls == 1


def test_classifier_rejects_caller_claim_that_conflicts_with_evidence() -> None:
    record = ResearchRunRecord(
        run_id="run-1",
        paper_id="paper-1",
        result=_result(status="halted"),
        disposition=ResearchRunDisposition.ACCEPTED,
    )
    with pytest.raises(ValueError):
        classify_research_run_record(
            replace(record),
            require_publication_authority=False,
        )


def test_reconciler_preserves_strong_v2_quarantine_in_memory_store() -> None:
    candidate = ResearchRunRecord(
        run_id="run-missing-authority",
        paper_id="paper-1",
        result=_result(run_id="run-missing-authority"),
        schema_version="newsroom.research_run_record.v2",
    )
    store = InMemoryResearchRunStore()
    reconciler = ResearchRunDispositionReconciler(
        run_store=store,
        recovery_source=_RecoverySource(candidate),
        max_runs=1,
    )

    recovered = reconciler.reconcile_run(candidate.run_id)
    assert recovered is not None
    assert recovered.quarantined
    assert (
        recovered.disposition_reason
        == ResearchRunDispositionReason.PUBLICATION_AUTHORITY_MISSING.value
    )
    assert store.get_latest_by_paper_id(candidate.paper_id) is None


def test_reconciler_rejects_existing_scope_or_paper_mismatch() -> None:
    candidate = ResearchRunRecord(
        run_id="run-existing",
        paper_id="paper-1",
        result=_result(run_id="run-existing"),
    )
    store = InMemoryResearchRunStore()
    store.save(candidate)
    reconciler = ResearchRunDispositionReconciler(
        run_store=store,
        recovery_source=_RecoverySource(candidate),
        max_runs=1,
    )

    with pytest.raises(ValueError, match="another paper"):
        reconciler.reconcile_run(candidate.run_id, expected_paper_id="paper-2")
    with pytest.raises(ValueError, match="another identity scope"):
        reconciler.reconcile_run(
            candidate.run_id,
            identity_scope_ref="sha256:" + "e" * 64,
        )


def test_reconciler_rejects_recovered_v2_scope_mismatch() -> None:
    scope = {"memory_namespace": "research:tenant:a"}
    candidate = ResearchRunRecord(
        run_id="run-v2-scope-mismatch",
        paper_id="paper-1",
        result=_result(
            run_id="run-v2-scope-mismatch",
            status="failed",
            scope=scope,
        ),
        identity_scope_ref=research_identity_scope_ref(scope),
        schema_version="newsroom.research_run_record.v2",
    )
    reconciler = ResearchRunDispositionReconciler(
        run_store=InMemoryResearchRunStore(),
        recovery_source=_RecoverySource(candidate),
        max_runs=1,
    )

    with pytest.raises(ValueError, match="another identity scope"):
        reconciler.reconcile_run(
            candidate.run_id,
            identity_scope_ref=research_identity_scope_ref(
                {"memory_namespace": "research:tenant:b"}
            ),
        )


@pytest.mark.parametrize(
    "run_ids",
    [
        "run-1",
        ("run-1", "run-1"),
        ("",),
        (1,),
    ],
)
def test_reconciler_rejects_unbounded_or_malformed_pending_ids(run_ids) -> None:
    class _InvalidSource(_RecoverySource):
        def list_pending_run_ids(self, *, limit: int):
            return run_ids

    candidate = ResearchRunRecord(
        run_id="run-1",
        paper_id="paper-1",
        result=_result(),
    )
    reconciler = ResearchRunDispositionReconciler(
        run_store=InMemoryResearchRunStore(),
        recovery_source=_InvalidSource(candidate),
        max_runs=2,
    )
    with pytest.raises(ValueError, match="bounded run list"):
        reconciler.reconcile_pending()


def test_reconciler_uses_supplied_legacy_scope_as_fallback_evidence() -> None:
    result = _result(run_id="run-legacy-scope")
    result.pop("actor_scope")
    result["trace"].pop("metadata")
    candidate = ResearchRunRecord(
        run_id="run-legacy-scope",
        paper_id="paper-1",
        result=result,
        schema_version="newsroom.research_run_record.v1",
    )
    scope_ref = research_identity_scope_ref({"memory_namespace": "research.public"})
    store = InMemoryResearchRunStore()
    reconciler = ResearchRunDispositionReconciler(
        run_store=store,
        recovery_source=_RecoverySource(candidate),
        max_runs=1,
    )

    recovered = reconciler.reconcile_run(
        candidate.run_id,
        identity_scope_ref=scope_ref,
    )
    assert recovered is not None and recovered.accepted
    assert recovered.identity_scope_ref == scope_ref
