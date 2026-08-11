from __future__ import annotations

from pathlib import Path
from datetime import timedelta

import pytest

from framework.events.canonical import checksum_for
from framework.harness import (
    ArtifactWriteRequest,
    HarnessSideEffectDecision,
    HarnessSideEffectDisposition,
    HarnessSideEffectIntent,
    HarnessSideEffectOrigin,
    InMemoryHarnessSideEffectStore,
)
from framework.shared.time import utc_now
from framework.workflow.runtime.manifest import manifest_hash

from business.research.ports.artifact_publication import (
    RESEARCH_ARTIFACT_EFFECT_KIND,
    RESEARCH_ARTIFACT_HANDLER_REF,
    RESEARCH_ARTIFACT_SCHEMA_VERSION,
    ResearchArtifactReadResolution,
)
from infrastructure.research.artifact_port import (
    ArtifactPublicationVisibilityError,
    ArtifactWriteConflictError,
    FilesystemHarnessArtifactPort,
)
from infrastructure.research.artifact_publication import ResearchArtifactBundleHandler


_IDENTITY_SCOPE = checksum_for({"tenant_id": "tenant-a", "user_id": "user-a"})
_SUBJECT_SCOPE = checksum_for({"paper_id": "paper-a"})


def test_prepare_is_hidden_until_controller_terminal_publication(tmp_path: Path) -> None:
    port, store, handler = _handler(tmp_path)
    intent, decision = _worker_authority()

    with port.bind_run(intent.run_id):
        store.put_decision(decision)
        prepared = handler.prepare(intent, decision)
        store.put_outcome(prepared)

        assert prepared.disposition is HarnessSideEffectDisposition.PREPARED
        assert prepared.candidate_refs
        assert not (tmp_path / intent.run_id / "manifest.json").exists()
        assert not (tmp_path / intent.run_id / "artifacts").exists()
        with pytest.raises(Exception):
            port.read_artifact(f"artifact://{intent.run_id}/research-analysis")

        terminal_intent, terminal_decision = _terminal_authority(prepared)
        store.put_decision(terminal_decision)
        published = handler.commit(terminal_intent, terminal_decision)

    assert published.disposition is HarnessSideEffectDisposition.ACCEPTED
    assert set(published.metadata["artifact_refs"]) == {
        "research-analysis",
        "research-quality-result",
        "harness-trace",
        "harness-transcript",
    }
    manifest = port.manager.read_run_manifest(intent.run_id)
    assert manifest["publication_authority_ref"] == terminal_decision.checksum
    assert manifest["terminal_side_effect_outcome_ref"] == published.checksum
    assert manifest["status"] == "succeeded"
    port.set_accepted_run_resolver(None)
    with pytest.raises(Exception, match="accepted run disposition"):
        port.read_artifact(f"artifact://{intent.run_id}/research-analysis")
    port.set_accepted_run_resolver(lambda *_args: True)
    assert port.read_artifact(
        f"artifact://{intent.run_id}/research-analysis"
    )["payload"] == {"paper_id": "paper-a"}
    assert not list((tmp_path / intent.run_id / ".rc").rglob("*.json"))


def test_terminal_publication_preserves_verified_context_ref_only_artifact(
    tmp_path: Path,
) -> None:
    port, store, handler = _handler(tmp_path)
    intent, decision = _worker_authority()
    identity = checksum_for({"context": "source"})
    artifact_type = f"context-source-snapshot-{identity.removeprefix('sha256:')}"

    with port.bind_run(intent.run_id):
        store.put_decision(decision)
        prepared = handler.prepare(intent, decision)
        store.put_outcome(prepared)
        port.write_artifact(
            ArtifactWriteRequest(
                artifact_type=artifact_type,
                payload={"snapshot": "verified"},
                metadata={
                    "context_ref_only": True,
                    "identity_checksum": identity,
                },
            )
        )
        terminal_intent, terminal_decision = _terminal_authority(prepared)
        store.put_decision(terminal_decision)
        published = handler.commit(terminal_intent, terminal_decision)

    assert published.disposition is HarnessSideEffectDisposition.ACCEPTED
    manifest = port.manager.read_run_manifest(intent.run_id)
    assert artifact_type in manifest["artifacts"]
    assert "research-analysis" in manifest["artifacts"]


def test_terminal_publication_rejects_spoofed_context_ref_only_artifact(
    tmp_path: Path,
) -> None:
    port, store, handler = _handler(tmp_path)
    intent, decision = _worker_authority()
    identity = checksum_for({"context": "spoofed"})

    with port.bind_run(intent.run_id):
        store.put_decision(decision)
        prepared = handler.prepare(intent, decision)
        store.put_outcome(prepared)
        port.write_artifact(
            ArtifactWriteRequest(
                artifact_type=(
                    "context-unregistered-" + identity.removeprefix("sha256:")
                ),
                payload={"snapshot": "spoofed"},
                metadata={
                    "context_ref_only": True,
                    "identity_checksum": identity,
                },
            )
        )
        terminal_intent, terminal_decision = _terminal_authority(prepared)
        store.put_decision(terminal_decision)
        with pytest.raises(ArtifactWriteConflictError, match="pre-existing"):
            handler.commit(terminal_intent, terminal_decision)


def test_nth_prepare_failure_removes_owned_candidates_without_visibility(
    tmp_path: Path,
) -> None:
    def fail(index: int, _artifact_type: str, phase: str) -> None:
        if phase == "prepare" and index == 2:
            raise RuntimeError("injected second candidate failure")

    port, store, handler = _handler(tmp_path, failure_injector=fail)
    intent, decision = _worker_authority()
    with port.bind_run(intent.run_id):
        store.put_decision(decision)
        with pytest.raises(RuntimeError, match="second candidate"):
            handler.prepare(intent, decision)

    run_dir = tmp_path / intent.run_id
    assert not (run_dir / "manifest.json").exists()
    assert not (run_dir / "artifacts").exists()
    assert not list(run_dir.rglob("*.json"))


def test_nth_terminal_failure_has_zero_canonical_visibility(
    tmp_path: Path,
) -> None:
    def fail(index: int, _artifact_type: str, phase: str) -> None:
        if phase == "commit" and index == 3:
            raise RuntimeError("injected terminal member failure")

    port, store, handler = _handler(tmp_path, failure_injector=fail)
    intent, decision = _worker_authority()
    with port.bind_run(intent.run_id):
        store.put_decision(decision)
        prepared = handler.prepare(intent, decision)
        store.put_outcome(prepared)
        terminal_intent, terminal_decision = _terminal_authority(prepared)
        store.put_decision(terminal_decision)
        with pytest.raises(RuntimeError, match="terminal member"):
            handler.commit(terminal_intent, terminal_decision)

    run_dir = tmp_path / intent.run_id
    assert not (run_dir / "manifest.json").exists()
    assert not list((run_dir / "artifacts").glob("*.json"))
    assert list((run_dir / ".rc").rglob("*.json"))


def test_terminal_retry_reconstructs_exact_outcome_from_manifest(tmp_path: Path) -> None:
    port, store, handler = _handler(tmp_path)
    intent, decision = _worker_authority()
    with port.bind_run(intent.run_id):
        store.put_decision(decision)
        prepared = handler.prepare(intent, decision)
        store.put_outcome(prepared)
        terminal_intent, terminal_decision = _terminal_authority(prepared)
        store.put_decision(terminal_decision)
        first = handler.commit(terminal_intent, terminal_decision)
        second = handler.commit(terminal_intent, terminal_decision)

    assert second == first
    assert handler.commit_calls == 2


def test_terminal_manifest_write_crash_keeps_visibility_for_idempotent_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port, store, handler = _handler(tmp_path)
    intent, decision = _worker_authority()
    with port.bind_run(intent.run_id):
        store.put_decision(decision)
        prepared = handler.prepare(intent, decision)
        store.put_outcome(prepared)
        terminal_intent, terminal_decision = _terminal_authority(prepared)
        store.put_decision(terminal_decision)
        original_write_json = port.manager.write_json
        raised = False

        def write_then_crash(*args, **kwargs):
            nonlocal raised
            result = original_write_json(*args, **kwargs)
            if not raised and args[1] == "manifest.json":
                raised = True
                raise OSError("crash after manifest replace")
            return result

        monkeypatch.setattr(port.manager, "write_json", write_then_crash)
        with pytest.raises(OSError, match="crash after manifest"):
            handler.commit(terminal_intent, terminal_decision)
        assert (tmp_path / intent.run_id / "manifest.json").is_file()
        assert list((tmp_path / intent.run_id / "artifacts").glob("*.json"))

        monkeypatch.setattr(port.manager, "write_json", original_write_json)
        recovered = handler.commit(terminal_intent, terminal_decision)

    assert recovered.disposition is HarnessSideEffectDisposition.ACCEPTED
    assert not list((tmp_path / intent.run_id / ".rc").rglob("*.json"))


def test_prepare_retry_reuses_durable_outcome_without_rewriting_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port, store, handler = _handler(tmp_path)
    intent, decision = _worker_authority()
    with port.bind_run(intent.run_id):
        store.put_decision(decision)
        first = handler.prepare(intent, decision)
        store.put_outcome(first)

    candidate_paths = tuple(
        tmp_path / intent.run_id / member["candidate_path"]
        for member in first.metadata["members"]
    )
    candidate_bytes = tuple(path.read_bytes() for path in candidate_paths)

    def fail_rewrite(*_args, **_kwargs):
        raise AssertionError("idempotent prepare must not rewrite candidate bytes")

    monkeypatch.setattr(port.manager, "write_bytes", fail_rewrite)
    second = handler.prepare(intent, decision)

    assert second == first
    assert tuple(path.read_bytes() for path in candidate_paths) == candidate_bytes


def test_cleanup_candidates_quarantines_expired_prepared_before_deleting(
    tmp_path: Path,
) -> None:
    port, store, handler = _handler(tmp_path)
    intent, decision = _worker_authority()
    with port.bind_run(intent.run_id):
        store.put_decision(decision)
        prepared = handler.prepare(intent, decision)
        store.put_outcome(prepared)
    assert prepared.retention_until is not None
    assert list((tmp_path / intent.run_id / ".rc").rglob("*.json"))

    cleaned = handler.cleanup_candidates(
        intent.run_id,
        now=prepared.retention_until + timedelta(seconds=1),
    )

    quarantined = store.get_outcome(
        effect_id=intent.effect_id,
        identity_scope_ref=intent.identity_scope_ref,
        subject_scope_ref=intent.subject_scope_ref,
        idempotency_key=intent.idempotency_key,
    )
    assert cleaned == (intent.effect_id,)
    assert quarantined is not None
    assert quarantined.disposition is HarnessSideEffectDisposition.QUARANTINE
    assert not list((tmp_path / intent.run_id / ".rc").rglob("*.json"))
    assert not (tmp_path / intent.run_id / "manifest.json").exists()


def test_cleanup_consumed_prepared_bytes_without_marking_them_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port, store, handler = _handler(tmp_path)
    intent, decision = _worker_authority()
    with port.bind_run(intent.run_id):
        store.put_decision(decision)
        prepared = handler.prepare(intent, decision)
        store.put_outcome(prepared)
        terminal_intent, terminal_decision = _terminal_authority(prepared)
        store.put_decision(terminal_decision)
        cleanup = handler._cleanup_candidate_paths
        monkeypatch.setattr(handler, "_cleanup_candidate_paths", lambda _paths: None)
        published = handler.commit(terminal_intent, terminal_decision)
        store.put_outcome(published)

    assert prepared.checksum in published.metadata["prepared_outcome_refs"]
    assert list((tmp_path / intent.run_id / ".rc").rglob("*.json"))
    monkeypatch.setattr(handler, "_cleanup_candidate_paths", cleanup)
    cleaned = handler.cleanup_candidates(intent.run_id)

    retained = store.get_outcome(
        effect_id=intent.effect_id,
        identity_scope_ref=intent.identity_scope_ref,
        subject_scope_ref=intent.subject_scope_ref,
        idempotency_key=intent.idempotency_key,
    )
    assert cleaned == (intent.effect_id,)
    assert retained == prepared
    assert retained.disposition is HarnessSideEffectDisposition.PREPARED
    assert not list((tmp_path / intent.run_id / ".rc").rglob("*.json"))


def test_v2_reader_claim_round_trip_binds_all_publication_evidence(
    tmp_path: Path,
) -> None:
    claims: list[tuple[object, ...]] = []
    port, store, handler = _handler(
        tmp_path,
        accepted_run_resolver=lambda *args: (claims.append(args) or True),
    )
    intent, decision = _worker_authority()
    with port.bind_run(intent.run_id):
        store.put_decision(decision)
        prepared = handler.prepare(intent, decision)
        store.put_outcome(prepared)
        terminal_intent, terminal_decision = _terminal_authority(prepared)
        store.put_decision(terminal_decision)
        published = handler.commit(terminal_intent, terminal_decision)

    assert port.read_artifact(
        f"artifact://{intent.run_id}/research-analysis"
    )["payload"] == {"paper_id": "paper-a"}
    assert len(claims) == 1
    (
        claim_run_id,
        claim_identity,
        claim_subject,
        claim_authority,
        claim_artifact_evidence,
        claim_outcome,
        claim_members,
    ) = claims[0]
    manifest = port.manager.read_run_manifest(intent.run_id)
    assert claim_run_id == intent.run_id
    assert claim_identity == intent.identity_scope_ref
    assert claim_subject == intent.subject_scope_ref
    assert claim_authority == terminal_decision.checksum
    assert claim_artifact_evidence == manifest["artifact_evidence_ref"]
    assert claim_outcome == published.checksum
    assert dict(claim_members) == {
        key: f"sha256:{item['checksum']}"
        for key, item in manifest["artifact_metadata"].items()
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("artifact_member_evidence_ref", "sha256:" + "0" * 64),
        ("subject_scope_ref", checksum_for({"paper_id": "other-paper"})),
    ],
)
def test_v2_reader_rejects_rehashed_manifest_tampering(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    port, store, handler = _handler(tmp_path)
    intent, decision = _worker_authority()
    with port.bind_run(intent.run_id):
        store.put_decision(decision)
        prepared = handler.prepare(intent, decision)
        store.put_outcome(prepared)
        terminal_intent, terminal_decision = _terminal_authority(prepared)
        store.put_decision(terminal_decision)
        handler.commit(terminal_intent, terminal_decision)

    manifest_path = tmp_path / intent.run_id / "manifest.json"
    manifest = port.manager.read_run_manifest(intent.run_id)
    manifest[field] = value
    manifest["manifest_hash"] = manifest_hash(manifest)
    port.manager.write_json(intent.run_id, "manifest.json", manifest)

    with pytest.raises(Exception, match="(?:evidence|authority) mismatch"):
        port.read_artifact(f"artifact://{intent.run_id}/research-analysis")


def test_v2_reader_rejects_member_byte_tamper_before_authorization(
    tmp_path: Path,
) -> None:
    port, store, handler = _handler(tmp_path)
    intent, decision = _worker_authority()
    with port.bind_run(intent.run_id):
        store.put_decision(decision)
        prepared = handler.prepare(intent, decision)
        store.put_outcome(prepared)
        terminal_intent, terminal_decision = _terminal_authority(prepared)
        store.put_decision(terminal_decision)
        handler.commit(terminal_intent, terminal_decision)

    (tmp_path / intent.run_id / "artifacts" / "research-analysis.json").write_bytes(
        b"tampered"
    )
    with pytest.raises(Exception, match="checksum mismatch"):
        port.read_artifact(f"artifact://{intent.run_id}/research-analysis")


def test_failed_legacy_manifest_is_non_destructive_and_diagnostic_only(
    tmp_path: Path,
) -> None:
    accepted_calls: list[object] = []
    diagnostic_calls: list[object] = []
    port = FilesystemHarnessArtifactPort(
        tmp_path,
        accepted_run_resolver=lambda claim: (accepted_calls.append(claim) or False),
        diagnostic_run_resolver=lambda claim: (
            diagnostic_calls.append(claim) or claim.disposition == "legacy_quarantined"
        ),
    )
    with port.bind_run("legacy-run"):
        ref = port.write_artifact(
            ArtifactWriteRequest(
                "research-analysis",
                {"status": "failed"},
                metadata={"run_id": "legacy-run"},
            )
        )
    manifest_path = tmp_path / "legacy-run" / "manifest.json"
    before = manifest_path.read_bytes()
    manifest = port.manager.read_run_manifest("legacy-run")
    manifest["status"] = "failed"
    manifest["manifest_hash"] = manifest_hash(manifest)
    port.manager.write_json("legacy-run", "manifest.json", manifest)
    failed_manifest = manifest_path.read_bytes()

    with pytest.raises(ArtifactPublicationVisibilityError) as error:
        port.read_artifact(ref.ref)
    assert error.value.disposition == "legacy_quarantined"
    assert accepted_calls == []
    assert port.read_diagnostic_artifact(
        ref.ref,
        identity_scope_ref=_IDENTITY_SCOPE,
        subject_scope_ref=_SUBJECT_SCOPE,
    )["payload"] == {"status": "failed"}
    assert diagnostic_calls[0].disposition == "legacy_quarantined"
    assert manifest_path.read_bytes() == failed_manifest
    assert failed_manifest != before


def test_legacy_reader_requires_an_unambiguous_single_scope_binding(
    tmp_path: Path,
) -> None:
    writer = FilesystemHarnessArtifactPort(tmp_path)
    with writer.bind_run("legacy-run"):
        ref = writer.write_artifact(
            ArtifactWriteRequest(
                "research-analysis",
                {"status": "succeeded"},
                metadata={"run_id": "legacy-run"},
            )
        )
    manifest_path = tmp_path / "legacy-run" / "manifest.json"
    original_bytes = manifest_path.read_bytes()

    shared_root_reader = FilesystemHarnessArtifactPort(
        tmp_path,
        accepted_run_resolver=lambda *_args: True,
    )
    with pytest.raises(ArtifactPublicationVisibilityError) as missing_scope:
        shared_root_reader.read_artifact(ref.ref)
    assert missing_scope.value.disposition == "legacy_quarantined"

    accepted_record_reader = FilesystemHarnessArtifactPort(
        tmp_path,
        accepted_run_resolver=lambda _claim: ResearchArtifactReadResolution(
            accepted=True,
            identity_scope_ref=_IDENTITY_SCOPE,
        ),
    )
    assert accepted_record_reader.read_artifact(ref.ref)["payload"] == {
        "status": "succeeded"
    }

    single_scope_reader = FilesystemHarnessArtifactPort(
        tmp_path,
        accepted_run_resolver=lambda claim: (
            claim.identity_scope_ref == _IDENTITY_SCOPE
            and claim.artifact_evidence_ref is not None
            and bool(claim.member_checksums)
        ),
        legacy_identity_scope_ref=_IDENTITY_SCOPE,
    )
    assert single_scope_reader.read_artifact(ref.ref)["payload"] == {
        "status": "succeeded"
    }
    assert manifest_path.read_bytes() == original_bytes


def test_legacy_reader_quarantines_conflicting_manifest_and_root_scope(
    tmp_path: Path,
) -> None:
    writer = FilesystemHarnessArtifactPort(tmp_path)
    with writer.bind_run("legacy-run"):
        ref = writer.write_artifact(
            ArtifactWriteRequest("research-analysis", {"status": "succeeded"})
        )
    manifest_path = tmp_path / "legacy-run" / "manifest.json"
    manifest = writer.manager.read_run_manifest("legacy-run")
    manifest["identity_scope_ref"] = checksum_for({"tenant_id": "other"})
    manifest["manifest_hash"] = manifest_hash(manifest)
    writer.manager.write_json("legacy-run", "manifest.json", manifest)
    conflicting_bytes = manifest_path.read_bytes()

    reader = FilesystemHarnessArtifactPort(
        tmp_path,
        accepted_run_resolver=lambda *_args: True,
        legacy_identity_scope_ref=_IDENTITY_SCOPE,
    )
    with pytest.raises(ArtifactPublicationVisibilityError) as conflict:
        reader.read_artifact(ref.ref)
    assert conflict.value.disposition == "legacy_quarantined"
    assert manifest_path.read_bytes() == conflicting_bytes


def test_diagnostic_reader_is_scope_bound_and_does_not_fallback(
    tmp_path: Path,
) -> None:
    port = FilesystemHarnessArtifactPort(tmp_path)
    with port.bind_run("legacy-run"):
        ref = port.write_artifact(ArtifactWriteRequest("research-analysis", {"x": 1}))
    scoped = FilesystemHarnessArtifactPort(
        tmp_path,
        diagnostic_run_resolver=lambda claim: claim.identity_scope_ref == _IDENTITY_SCOPE,
    )
    with pytest.raises(ArtifactPublicationVisibilityError):
        scoped.read_diagnostic_artifact(
            ref.ref,
            identity_scope_ref=checksum_for({"tenant_id": "wrong"}),
        )
    with pytest.raises(ArtifactPublicationVisibilityError):
        port.read_diagnostic_artifact(ref.ref, identity_scope_ref=_IDENTITY_SCOPE)


def _handler(
    root: Path,
    *,
    failure_injector=None,
    accepted_run_resolver=None,
) -> tuple[
    FilesystemHarnessArtifactPort,
    InMemoryHarnessSideEffectStore,
    ResearchArtifactBundleHandler,
]:
    port = FilesystemHarnessArtifactPort(
        root,
        accepted_run_resolver=(
            accepted_run_resolver
            if accepted_run_resolver is not None
            else (lambda *_args: True)
        ),
    )
    store = InMemoryHarnessSideEffectStore()
    handler = ResearchArtifactBundleHandler(
        artifact_port=port,
        side_effect_store=store,
        terminal_payload_factory=lambda cutoff: (
            ArtifactWriteRequest(
                "harness-trace",
                {"run_id": "run-a", "cutoff": cutoff},
                metadata={"run_id": "run-a"},
            ),
            ArtifactWriteRequest(
                "harness-transcript",
                {"run_id": "run-a", "entries": []},
                metadata={"run_id": "run-a"},
            ),
        ),
        failure_injector=failure_injector,
    )
    return port, store, handler


def _worker_authority() -> tuple[HarnessSideEffectIntent, HarnessSideEffectDecision]:
    members = [
        ArtifactWriteRequest(
            "research-analysis",
            {"paper_id": "paper-a"},
            metadata={"run_id": "run-a"},
        ).to_dict(),
        ArtifactWriteRequest(
            "research-quality-result",
            {"passed": True},
            metadata={"run_id": "run-a"},
        ).to_dict(),
    ]
    intent = HarnessSideEffectIntent(
        effect_id="research-artifact-effect:worker-a",
        kind=RESEARCH_ARTIFACT_EFFECT_KIND,
        run_id="run-a",
        origin=HarnessSideEffectOrigin.WORKER,
        atomic_group="research-artifacts:group-a",
        identity_scope_ref=_IDENTITY_SCOPE,
        subject_scope_ref=_SUBJECT_SCOPE,
        step_id="publish_artifacts",
        worker_result_ref="worker-result://run-a/publish_artifacts/1",
        candidate_checksum=checksum_for({"members": members}),
        handler=RESEARCH_ARTIFACT_HANDLER_REF,
        payload={
            "schema_version": RESEARCH_ARTIFACT_SCHEMA_VERSION,
            "run_id": "run-a",
            "paper_id": "paper-a",
            "members": members,
        },
    )
    decision = HarnessSideEffectDecision(
        decision_id="research-artifact-decision:worker-a",
        intent_ref=intent.checksum,
        effect_id=intent.effect_id,
        kind=intent.kind,
        origin=intent.origin,
        run_id=intent.run_id,
        handler=RESEARCH_ARTIFACT_HANDLER_REF,
        identity_scope_ref=intent.identity_scope_ref,
        subject_scope_ref=intent.subject_scope_ref,
        atomic_group=intent.atomic_group,
        idempotency_key=intent.idempotency_key,
        command_ordinal=1,
        causation_id="command:worker-a",
        disposition=HarnessSideEffectDisposition.PREPARED,
        step_id="publish_artifacts",
        worker_result_ref=intent.worker_result_ref,
        gate_refs=("output_schema@1",),
        gate_result_refs=(checksum_for("gate-result"),),
        aggregate_verdict_ref=checksum_for("verdict"),
        approval_evidence_ref=checksum_for("not-required"),
        budget_ref=checksum_for("budget"),
        decided_at=utc_now(),
    )
    return intent, decision


def _terminal_authority(
    prepared,
) -> tuple[HarnessSideEffectIntent, HarnessSideEffectDecision]:
    intent = HarnessSideEffectIntent(
        effect_id="harness-terminal-effect:terminal-a",
        kind=RESEARCH_ARTIFACT_EFFECT_KIND,
        run_id="run-a",
        origin=HarnessSideEffectOrigin.CONTROLLER_TERMINAL,
        atomic_group=prepared.atomic_group,
        identity_scope_ref=_IDENTITY_SCOPE,
        subject_scope_ref=_SUBJECT_SCOPE,
        terminal_action="complete_run",
        state_checksum=checksum_for("state"),
        completion_input_ref=checksum_for("completion"),
        handler=RESEARCH_ARTIFACT_HANDLER_REF,
        payload={
            "prepared_outcome_refs": [prepared.checksum],
            "history_cutoff": "event-before-terminal",
        },
        candidate_refs=prepared.candidate_refs,
    )
    decision = HarnessSideEffectDecision(
        decision_id="research-artifact-decision:terminal-a",
        intent_ref=intent.checksum,
        effect_id=intent.effect_id,
        kind=intent.kind,
        origin=intent.origin,
        run_id=intent.run_id,
        handler=RESEARCH_ARTIFACT_HANDLER_REF,
        identity_scope_ref=intent.identity_scope_ref,
        subject_scope_ref=intent.subject_scope_ref,
        atomic_group=intent.atomic_group,
        idempotency_key=intent.idempotency_key,
        command_ordinal=2,
        causation_id="command:terminal-a",
        disposition=HarnessSideEffectDisposition.ACCEPTED,
        terminal_action="complete_run",
        terminal_state_ref=intent.state_checksum,
        gate_refs=("ResearchQualityGate@1",),
        gate_result_refs=(checksum_for("quality-gate-result"),),
        aggregate_verdict_ref=checksum_for("aggregate-verdict"),
        approval_evidence_ref=checksum_for("not-required-terminal"),
        budget_ref=checksum_for("terminal-budget"),
        decided_at=utc_now(),
    )
    return intent, decision
