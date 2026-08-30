from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from framework.events.canonical import checksum_for
from framework.harness import ArtifactWriteRequest, InMemoryHarnessEventPort

from backend.research.application.run_disposition import (
    ResearchRunDispositionReconciler,
)
from backend.research.application.analyze_paper import AnalyzePaperUseCase
from backend.research.application.single_paper_runtime import (
    AnalyzePaperRequest,
    ResearchAnalysisResult,
    ResearchSinglePaperRuntime,
)
from backend.research.ports.artifact_publication import (
    ResearchArtifactReadClaim,
    artifact_evidence_ref,
)
from backend.research.ports.run_store import (
    ResearchRunDisposition,
    ResearchRunRecord,
)
from infrastructure.research.artifact_port import (
    ArtifactPublicationVisibilityError,
    FilesystemHarnessArtifactPort,
)
from infrastructure.research.artifact_publication import ResearchArtifactBundleHandler
from infrastructure.research.filesystem_run_store import (
    FilesystemResearchRunStore,
    RESEARCH_RUN_RECORD_SCHEMA_VERSION,
    RESEARCH_RUN_RECORD_SCHEMA_VERSION_V2,
)
from infrastructure.storage.harness import SQLiteHarnessSideEffectStore
from interfaces.composition.research import (
    _DurableResearchRunRecoverySource,
    _research_artifact_diagnostic_is_authorized,
    _research_artifact_run_is_accepted,
    _resolve_research_artifact_run,
)
from interfaces.services.research_service import (
    ResearchActorInput,
    ResearchAnalyzeInput,
    ResearchApplicationService,
    ResearchServiceError,
)
from tests.backend.research.fakes import (
    FakeGithubRepositoryPort,
    FakeResearchDocumentCompiler,
    FakeResearchLLMWorker,
    FakeResearchRAGRuntime,
    FakeResearchSourceProvider,
    in_memory_node_output_resource_factory,
)
from tests.interfaces.research_fixtures import (
    FakeResearchAnalysisResult,
    make_research_result,
)


class _CountingResearchLLMWorker(FakeResearchLLMWorker):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def generate_candidate(
        self,
        *,
        task: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls += 1
        return super().generate_candidate(task=task, payload=payload)


class _RaisedResearchLLMWorker(FakeResearchLLMWorker):
    def generate_candidate(
        self,
        *,
        task: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        del task, payload
        raise RuntimeError("injected candidate worker failure")


class _HistoryReader:
    def __init__(self, history, *, graph_recovery=None, graph_available: bool = True) -> None:
        self._history = tuple(history)
        self._graph_recovery = graph_recovery
        self._graph_available = graph_available
        self.read_calls = 0

    def read_history(self, _run_id: str):
        self.read_calls += 1
        return self._history

    def recover_graph(self, run_id: str):
        if not callable(self._graph_recovery) or not self._graph_available:
            return type("MissingGraphRecovery", (), {"state": None})()
        return self._graph_recovery(run_id)


@pytest.fixture(scope="module")
def published_recovery_evidence(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("research-recovery-composition")
    event_port = InMemoryHarnessEventPort()
    artifact_port = FilesystemHarnessArtifactPort(
        root / "artifacts",
        accepted_run_resolver=lambda *_args: True,
    )
    side_effect_store = SQLiteHarnessSideEffectStore(root / "effects.sqlite3")
    llm_worker = _CountingResearchLLMWorker()
    handlers: list[ResearchArtifactBundleHandler] = []

    def handler_factory(**kwargs: Any) -> ResearchArtifactBundleHandler:
        handler = ResearchArtifactBundleHandler(**kwargs)
        handlers.append(handler)
        return handler

    runtime = ResearchSinglePaperRuntime(
        source_provider=FakeResearchSourceProvider(),
        document_compiler=FakeResearchDocumentCompiler(),
        llm_worker=llm_worker,
        github_repository=FakeGithubRepositoryPort(),
        rag_runtime=FakeResearchRAGRuntime(),
        artifact_port=artifact_port,
        event_port_factory=lambda _run_id: event_port,
        side_effect_store=side_effect_store,
        artifact_handler_factory=handler_factory,
        node_output_resource_factory=in_memory_node_output_resource_factory,
    )
    run_id = "research-composition-recovery"
    result = runtime.run(
        AnalyzePaperRequest(
            run_id=run_id,
            paper_id="paper-harness-001",
            source_ref="https://arxiv.org/abs/2606.00123",
            user_id="user-publication",
            memory_namespace="research:user:user-publication",
        )
    )
    baseline = {
        "llm_calls": llm_worker.calls,
        "prepare_calls": sum(handler.prepare_calls for handler in handlers),
        "commit_calls": sum(handler.commit_calls for handler in handlers),
    }
    try:
        yield {
            "root": root,
            "run_id": run_id,
            "result": result,
            "event_port": event_port,
            "artifact_port": artifact_port,
            "side_effect_store": side_effect_store,
            "llm_worker": llm_worker,
            "handlers": handlers,
            "baseline": baseline,
        }
    finally:
        side_effect_store.close()


def test_startup_and_lazy_recovery_write_v2_without_worker_or_effect_calls(
    published_recovery_evidence: dict[str, Any],
) -> None:
    evidence = published_recovery_evidence
    run_id = evidence["run_id"]
    artifact_port = evidence["artifact_port"]
    side_effect_store = evidence["side_effect_store"]
    event_port = evidence["event_port"]

    startup_store = _v2_store(evidence["root"] / "startup-store")
    startup_source = _DurableResearchRunRecoverySource(
        artifact_port=artifact_port,
        run_store=startup_store,
        side_effect_store=side_effect_store,
        scoped_event_port_factory=lambda _run_id, _metadata: event_port,
    )
    startup_reconciler = ResearchRunDispositionReconciler(
        run_store=startup_store,
        recovery_source=startup_source,
        max_runs=10,
    )
    service = ResearchApplicationService(
        run_store=startup_store,
        run_reconciler=startup_reconciler,
    )

    recovered = startup_store.get_by_run_id(run_id)
    assert recovered is not None
    assert recovered.disposition is ResearchRunDisposition.ACCEPTED
    assert recovered.schema_version == RESEARCH_RUN_RECORD_SCHEMA_VERSION_V2
    assert startup_reconciler.reconcile_pending() == ()
    assert service.get_trace(
        run_id,
        actor=ResearchActorInput(
            user_id="user-publication",
            memory_namespace="research:user:user-publication",
        ),
    )["status"] == "succeeded"

    lazy_store = _v2_store(evidence["root"] / "lazy-store")
    lazy_source = _DurableResearchRunRecoverySource(
        artifact_port=artifact_port,
        run_store=lazy_store,
        side_effect_store=side_effect_store,
        scoped_event_port_factory=lambda _run_id, _metadata: event_port,
    )
    lazy_reconciler = ResearchRunDispositionReconciler(
        run_store=lazy_store,
        recovery_source=lazy_source,
        max_runs=10,
    )
    artifact_port.set_accepted_run_resolver(
        lambda claim: (
            _research_artifact_run_is_accepted(
                lazy_store,
                claim=claim,
                reconciler=lazy_reconciler,
            )
        )
    )
    restored_artifact = artifact_port.read_artifact(
        f"artifact://{run_id}/research-analysis"
    )
    assert restored_artifact["payload"]["paper_id"] == "paper-harness-001"
    assert lazy_store.get_by_run_id(run_id).accepted is True
    _assert_recovery_has_no_live_calls(evidence)


def test_inflight_terminal_publication_is_deferred_until_success_transition(
    published_recovery_evidence: dict[str, Any],
) -> None:
    evidence = published_recovery_evidence
    full_history = evidence["event_port"].read_history(evidence["run_id"])
    truncated = tuple(
        event
        for event in full_history
        if not (
            event.event_type.value == "harness_transition_committed"
            and event.payload.get("transition_kind") == "success"
        )
        and not (
            event.event_type.value == "run_state_changed"
            and event.metadata.get("transition_kind") == "success"
        )
    )
    reader = _HistoryReader(
        truncated,
        graph_recovery=evidence["event_port"].recover_graph,
        graph_available=False,
    )
    store = _v2_store(evidence["root"] / "quarantine-store")
    source = _DurableResearchRunRecoverySource(
        artifact_port=evidence["artifact_port"],
        run_store=store,
        side_effect_store=evidence["side_effect_store"],
        scoped_event_port_factory=lambda _run_id, _metadata: reader,
    )
    reconciler = ResearchRunDispositionReconciler(
        run_store=store,
        recovery_source=source,
        max_runs=10,
    )

    recovered = reconciler.reconcile_run(evidence["run_id"])

    assert recovered is None
    assert store.get_by_run_id(evidence["run_id"]) is None
    assert store.get_latest_by_paper_id("paper-harness-001") is None
    assert reader.read_calls == 1

    completed_reader = _HistoryReader(
        full_history,
        graph_recovery=evidence["event_port"].recover_graph,
    )
    completed_source = _DurableResearchRunRecoverySource(
        artifact_port=evidence["artifact_port"],
        run_store=store,
        side_effect_store=evidence["side_effect_store"],
        scoped_event_port_factory=lambda _run_id, _metadata: completed_reader,
    )
    completed_reconciler = ResearchRunDispositionReconciler(
        run_store=store,
        recovery_source=completed_source,
        max_runs=10,
    )

    completed = completed_reconciler.reconcile_run(evidence["run_id"])

    assert completed is not None
    assert completed.disposition is ResearchRunDisposition.ACCEPTED
    assert completed.result.status == "succeeded"
    assert store.get_latest_by_paper_id(completed.paper_id).run_id == completed.run_id
    assert completed_reader.read_calls == 1
    _assert_recovery_has_no_live_calls(evidence)


@pytest.mark.parametrize("failure_stage", ["worker", "prepare", "terminal"])
def test_real_post_creation_exception_commits_scoped_v2_quarantine(
    tmp_path: Path,
    failure_stage: str,
) -> None:
    run_id = f"research-real-{failure_stage}-failure"
    paper_id = "paper-harness-001"
    memory_namespace = "research:user:failure-recovery"
    event_port = InMemoryHarnessEventPort()
    artifact_port = FilesystemHarnessArtifactPort(tmp_path / "artifacts")
    side_effect_store = SQLiteHarnessSideEffectStore(tmp_path / "effects.sqlite3")
    run_store = _v2_store(tmp_path / "run-store")
    handlers: list[ResearchArtifactBundleHandler] = []

    def inject_failure(index: int, _artifact_type: str, phase: str) -> None:
        if failure_stage == "prepare" and phase == "prepare" and index == 1:
            raise RuntimeError("injected preparation failure")
        if failure_stage == "terminal" and phase == "commit" and index == 3:
            raise RuntimeError("injected terminal member failure")

    def handler_factory(**kwargs: Any) -> ResearchArtifactBundleHandler:
        handler = ResearchArtifactBundleHandler(
            **kwargs,
            failure_injector=inject_failure,
        )
        handlers.append(handler)
        return handler

    runtime = ResearchSinglePaperRuntime(
        source_provider=FakeResearchSourceProvider(),
        document_compiler=FakeResearchDocumentCompiler(),
        llm_worker=(
            _RaisedResearchLLMWorker()
            if failure_stage == "worker"
            else FakeResearchLLMWorker()
        ),
        github_repository=FakeGithubRepositoryPort(),
        rag_runtime=FakeResearchRAGRuntime(),
        artifact_port=artifact_port,
        event_port_factory=lambda _run_id: event_port,
        scoped_event_port_factory=lambda _run_id, _metadata: event_port,
        side_effect_store=side_effect_store,
        artifact_handler_factory=handler_factory,
        node_output_resource_factory=in_memory_node_output_resource_factory,
    )
    recovery_source = _DurableResearchRunRecoverySource(
        artifact_port=artifact_port,
        run_store=run_store,
        side_effect_store=side_effect_store,
        scoped_event_port_factory=lambda _run_id, _metadata: event_port,
    )
    reconciler = ResearchRunDispositionReconciler(
        run_store=run_store,
        recovery_source=recovery_source,
        max_runs=10,
    )
    service = ResearchApplicationService(
        analyze_use_case=AnalyzePaperUseCase(runtime),
        run_store=run_store,
        run_reconciler=reconciler,
    )
    command = ResearchAnalyzeInput(
        run_id=run_id,
        paper_id=paper_id,
        source_url="https://arxiv.org/abs/2606.00123",
        user_id="failure-recovery",
        memory_namespace=memory_namespace,
    )

    try:
        with pytest.raises(ResearchServiceError) as raised:
            service.analyze_paper(command)

        assert raised.value.code == "research_run_failed"
        assert raised.value.status_code == 500
        assert raised.value.details == {"error_type": "RuntimeError"}
        record = run_store.get_by_run_id(run_id)
        assert record is not None
        assert record.disposition is ResearchRunDisposition.QUARANTINE
        assert record.schema_version == RESEARCH_RUN_RECORD_SCHEMA_VERSION_V2
        assert record.result.status == "failed"
        assert record.result.artifact_refs == {}
        assert record.result.diagnostics["harness_status"] != "succeeded"
        assert (
            record.result.diagnostics["terminal_reason"]
            == "runtime_exception_after_durable_run"
        )
        assert (
            record.result.diagnostics["durable_history_cutoff"]
            == record.result.trace.events[-1].event_id
        )
        assert record.result.diagnostics["recovered_from_durable_history"] is True
        assert run_store.get_latest_by_paper_id(paper_id) is None
        assert not (artifact_port.root / run_id / "manifest.json").exists()

        handler_counts = [
            (handler.prepare_calls, handler.commit_calls) for handler in handlers
        ]
        reconciled_again = reconciler.reconcile_failed_run(
            AnalyzePaperRequest(
                run_id=run_id,
                paper_id=paper_id,
                source_ref="https://arxiv.org/abs/2606.00123",
                user_id="failure-recovery",
                memory_namespace=memory_namespace,
            ),
            identity_scope_ref=record.identity_scope_ref or "",
        )
        assert reconciled_again is not None
        assert reconciled_again.run_id == record.run_id
        assert reconciled_again.disposition is ResearchRunDisposition.QUARANTINE
        assert [
            (handler.prepare_calls, handler.commit_calls) for handler in handlers
        ] == handler_counts

        reopened_store = _v2_store(tmp_path / "run-store")
        reopened = ResearchApplicationService(run_store=reopened_store)
        trace = reopened.get_trace(
            run_id,
            actor=ResearchActorInput(
                user_id="failure-recovery",
                memory_namespace=memory_namespace,
            ),
        )
        assert trace["status"] == "failed"
        assert trace["metadata"]["artifactRefs"] == {}
    finally:
        side_effect_store.close()


def test_legacy_artifact_resolution_is_rejected(
    tmp_path: Path,
) -> None:
    run_id = "legacy-accepted-run"
    paper_id = "legacy-accepted-paper"
    result = make_research_result(run_id=run_id, paper_id=paper_id)
    artifact_refs = {
        artifact_type: f"artifact://{run_id}/{artifact_type}"
        for artifact_type in (
            "research-analysis",
            "research-reader-payload",
            "research-quality-result",
            "harness-trace",
            "harness-transcript",
        )
    }
    result.artifact_refs.clear()
    result.artifact_refs.update(artifact_refs)
    store = FilesystemResearchRunStore(
        tmp_path,
        result_decoder=FakeResearchAnalysisResult.from_dict,
    )
    store.save(ResearchRunRecord(run_id=run_id, paper_id=paper_id, result=result))
    record = store.get_by_run_id(run_id)
    assert record is not None and record.accepted

    claim = ResearchArtifactReadClaim(
        run_id=run_id,
        schema_version="newsroom.research-artifact-manifest/v1",
        identity_scope_ref=None,
        subject_scope_ref=None,
        publication_authority_ref=None,
        artifact_evidence_ref=artifact_evidence_ref(artifact_refs),
        terminal_side_effect_outcome_ref=None,
        artifact_refs=tuple(sorted(artifact_refs.items())),
        member_checksums=tuple(
            (artifact_type, "sha256:" + "a" * 64)
            for artifact_type in sorted(artifact_refs)
        ),
    )

    resolution = _resolve_research_artifact_run(store, claim=claim)
    assert resolution.accepted is False
    assert _research_artifact_run_is_accepted(store, claim=claim) is False


def test_service_diagnostic_artifact_read_is_quarantine_and_scope_bound(
    tmp_path: Path,
) -> None:
    run_id = "legacy-quarantine-run"
    paper_id = "legacy-quarantine-paper"
    scope = {
        "tenant_id": "tenant-diagnostic",
        "user_id": "user-diagnostic",
        "memory_namespace": "research:tenant:tenant-diagnostic:user:user-diagnostic",
    }
    artifact_port = FilesystemHarnessArtifactPort(tmp_path / "artifacts")
    with artifact_port.bind_run(run_id):
        artifact_ref = artifact_port.write_artifact(
            ArtifactWriteRequest(
                "research-analysis",
                {"status": "failed", "paper_id": paper_id},
                metadata={"run_id": run_id},
            )
        ).ref
    staged_before = artifact_port.list_staged_artifacts(run_id)

    result = make_research_result(
        run_id=run_id,
        paper_id=paper_id,
        status="halted",
        quality_passed=False,
    )
    result.artifact_refs.clear()
    result.artifact_refs["research-analysis"] = artifact_ref
    result.actor_scope.clear()
    result.actor_scope.update(scope)
    result.trace["metadata"] = dict(scope)
    for entry in result.transcript.get("entries", []):
        entry["metadata"] = dict(scope)

    run_store = FilesystemResearchRunStore(
        tmp_path / "runs",
        result_decoder=FakeResearchAnalysisResult.from_dict,
    )
    run_store.save(
        ResearchRunRecord(run_id=run_id, paper_id=paper_id, result=result)
    )
    quarantined = run_store.get_by_run_id(run_id)
    assert quarantined is not None and quarantined.quarantined
    artifact_port.set_accepted_run_resolver(
        lambda claim: _resolve_research_artifact_run(run_store, claim=claim)
    )
    artifact_port.set_diagnostic_run_resolver(
        lambda claim: _research_artifact_diagnostic_is_authorized(
            run_store,
            claim=claim,
        )
    )
    service = ResearchApplicationService(
        run_store=run_store,
        diagnostic_artifact_reader=artifact_port,
    )
    actor = ResearchActorInput(**scope)

    with pytest.raises(ArtifactPublicationVisibilityError) as hidden:
        artifact_port.read_artifact(artifact_ref)
    assert hidden.value.disposition == "staging_only"
    with pytest.raises(ResearchServiceError) as diagnostic:
        service.read_diagnostic_artifact(
            run_id,
            artifact_ref,
            actor=actor,
        )
    assert diagnostic.value.details == {
        "error_type": "ArtifactPublicationVisibilityError"
    }
    assert artifact_port.list_staged_artifacts(run_id) == staged_before

    with pytest.raises(ResearchServiceError) as foreign_scope:
        service.read_diagnostic_artifact(
            run_id,
            artifact_ref,
            actor=ResearchActorInput(
                tenant_id="tenant-diagnostic",
                user_id="other-user",
                memory_namespace=(
                    "research:tenant:tenant-diagnostic:user:other-user"
                ),
            ),
        )
    assert foreign_scope.value.code == "paper_not_found"
    with pytest.raises(ResearchServiceError) as unowned_ref:
        service.read_diagnostic_artifact(
            run_id,
            f"artifact://{run_id}/research-quality-result",
            actor=actor,
        )
    assert unowned_ref.value.status_code == 404

    accepted_run_id = "legacy-accepted-diagnostic-run"
    accepted = make_research_result(
        run_id=accepted_run_id,
        paper_id="legacy-accepted-diagnostic-paper",
    )
    accepted.actor_scope.clear()
    accepted.actor_scope.update(scope)
    accepted.trace["metadata"] = dict(scope)
    for entry in accepted.transcript.get("entries", []):
        entry["metadata"] = dict(scope)
    accepted.artifact_refs.clear()
    accepted.artifact_refs.update(
        {
            artifact_type: f"artifact://{accepted_run_id}/{artifact_type}"
            for artifact_type in (
                "research-analysis",
                "research-reader-payload",
                "research-quality-result",
                "harness-trace",
                "harness-transcript",
            )
        }
    )
    run_store.save(
        ResearchRunRecord(
            run_id=accepted_run_id,
            paper_id="legacy-accepted-diagnostic-paper",
            result=accepted,
        )
    )
    with pytest.raises(ResearchServiceError) as accepted_hidden:
        service.read_diagnostic_artifact(
            accepted_run_id,
            accepted.artifact_refs["research-analysis"],
            actor=actor,
        )
    assert accepted_hidden.value.status_code == 404


def _v2_store(root: Path) -> FilesystemResearchRunStore:
    return FilesystemResearchRunStore(
        root,
        result_decoder=ResearchAnalysisResult.from_dict,
        write_schema_version=RESEARCH_RUN_RECORD_SCHEMA_VERSION_V2,
        supported_schema_versions=(
            RESEARCH_RUN_RECORD_SCHEMA_VERSION,
            RESEARCH_RUN_RECORD_SCHEMA_VERSION_V2,
        ),
    )


def _assert_recovery_has_no_live_calls(evidence: dict[str, Any]) -> None:
    assert evidence["llm_worker"].calls == evidence["baseline"]["llm_calls"]
    assert sum(
        handler.prepare_calls for handler in evidence["handlers"]
    ) == evidence["baseline"]["prepare_calls"]
    assert sum(
        handler.commit_calls for handler in evidence["handlers"]
    ) == evidence["baseline"]["commit_calls"]
