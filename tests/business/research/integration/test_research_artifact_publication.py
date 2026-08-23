from __future__ import annotations

from dataclasses import fields, is_dataclass
from functools import partial
from pathlib import Path
from types import FunctionType, MappingProxyType, MethodType, ModuleType
from typing import Any

import pytest

from framework.harness import (
    ContextAssembler,
    HarnessEventType,
    HarnessSideEffectDisposition,
    HarnessSideEffectOrigin,
    HarnessWorkerResult,
    HarnessWorkerStatus,
    InMemoryHarnessEventPort,
    RunOutcome,
)
from framework.events.canonical import checksum_for
from framework.harness.control_plane.activity_execution import (
    HarnessGraphActivityTaskContext,
)
from framework.harness.control_plane.graph_runtime import HarnessGraphActivity
from framework.harness.graph.model import HarnessContractKind, HarnessContractReference
from framework.harness.graph.reference import HarnessGraphReference
from framework.harness.graph.versioning import (
    GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
    HARNESS_CONDITION_POLICY_VERSION,
    HARNESS_GRAPH_ONLY_COMPILER_VERSION,
)

from business.research.application.single_paper_runtime import (
    AnalyzePaperRequest,
    ResearchSinglePaperRuntime,
    _ResearchRunWorkspace,
)
from infrastructure.research.artifact_port import FilesystemHarnessArtifactPort
from infrastructure.research.artifact_publication import ResearchArtifactBundleHandler
from infrastructure.storage.harness import SQLiteHarnessSideEffectStore
from tests.business.research.fakes import (
    FakeGithubRepositoryPort,
    FakeResearchDocumentCompiler,
    FakeResearchLLMWorker,
    FakeResearchRAGRuntime,
    FakeResearchSourceProvider,
    in_memory_node_output_resource_factory,
)


def test_runtime_publication_is_terminal_and_sqlite_authoritative(tmp_path: Path) -> None:
    artifact_port = FilesystemHarnessArtifactPort(
        tmp_path / "artifacts",
        accepted_run_resolver=lambda *_args: True,
    )
    side_effect_store = SQLiteHarnessSideEffectStore(tmp_path / "effects.sqlite3")
    runtime = _runtime(
        artifact_port=artifact_port,
        side_effect_store=side_effect_store,
    )
    try:
        result = runtime.run(_request("research-publication-runtime"))
    finally:
        side_effect_store.close()

    assert result.succeeded is True
    assert {
        "research-analysis",
        "research-quality-result",
        "harness-trace",
        "harness-transcript",
    }.issubset(result.artifact_refs)
    manifest = artifact_port.read_terminal_manifest(result.run_id)
    assert manifest.publication is not None
    assert manifest.publication.publication_authority_ref == result.diagnostics[
        "publication_authority_ref"
    ]
    assert manifest.publication.terminal_side_effect_outcome_ref == result.diagnostics[
        "terminal_side_effect_outcome_ref"
    ]
    assert manifest.publication.artifact_evidence_ref == result.diagnostics[
        "artifact_evidence_ref"
    ]
    assert manifest.status == "succeeded"

    published_trace = artifact_port.read_artifact(
        result.artifact_refs["harness-trace"]
    )["payload"]
    cutoff = result.diagnostics["terminal_history_cutoff"]
    assert published_trace["events"][-1]["event_id"] == cutoff
    assert result.trace.events[-1].event_id == cutoff
    assert [item["event_id"] for item in published_trace["events"]] == [
        item.event_id for item in result.trace.events
    ]
    assert len(result.trace.events) == len(published_trace["events"])

    decisions = side_effect_store.list_decisions(run_id=result.run_id)
    assert [decision.origin for decision in decisions] == [
        HarnessSideEffectOrigin.WORKER,
        HarnessSideEffectOrigin.CONTROLLER_TERMINAL,
    ]
    assert not list(
        (artifact_port.root / result.run_id / ".rc").rglob("*.json")
    )


def test_publish_output_schema_failure_calls_no_handler_and_has_zero_visibility(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_id = "research-publication-output-schema-failed"
    artifact_port = FilesystemHarnessArtifactPort(tmp_path / "artifacts")
    side_effect_store = SQLiteHarnessSideEffectStore(tmp_path / "effects.sqlite3")
    event_port = InMemoryHarnessEventPort()
    handlers: list[ResearchArtifactBundleHandler] = []

    def handler_factory(**kwargs: Any) -> ResearchArtifactBundleHandler:
        handler = ResearchArtifactBundleHandler(**kwargs)
        handlers.append(handler)
        return handler

    def invalid_publish_output(
        _task: dict[str, Any],
        _workspace: _ResearchRunWorkspace,
    ) -> HarnessWorkerResult:
        return HarnessWorkerResult(
            status=HarnessWorkerStatus.SUCCEEDED,
            # `artifact_types` is required by the workflow's OutputSchemaGate.
            output={"artifact_bundle_ref": "sha256:" + "a" * 64},
        )

    monkeypatch.setattr(
        ResearchSinglePaperRuntime,
        "_publish_artifacts",
        staticmethod(invalid_publish_output),
    )
    runtime = _runtime(
        artifact_port=artifact_port,
        side_effect_store=side_effect_store,
        event_port=event_port,
        artifact_handler_factory=handler_factory,
    )
    try:
        result = runtime.run(_request(run_id))
    finally:
        side_effect_store.close()

    assert result.succeeded is False
    assert handlers
    assert sum(handler.prepare_calls for handler in handlers) == 0
    assert sum(handler.commit_calls for handler in handlers) == 0
    assert side_effect_store.list_decisions(run_id=run_id) == ()
    assert result.artifact_refs == {}
    run_dir = artifact_port.root / run_id
    manifest = artifact_port.read_terminal_manifest(run_id)
    assert manifest.status.value == result.status == "halted"
    assert manifest.publication is None
    assert manifest.artifacts == ()
    assert not (run_dir / "artifacts").exists()
    assert not (run_dir / ".rc").exists()


def test_terminal_manifest_recovery_reuses_effect_id_without_repeating_workers(
    tmp_path: Path,
) -> None:
    run_id = "research-publication-terminal-recovery"
    artifact_root = tmp_path / "artifacts"
    effects_path = tmp_path / "effects.sqlite3"
    event_port = InMemoryHarnessEventPort()
    artifact_port = FilesystemHarnessArtifactPort(
        artifact_root,
        accepted_run_resolver=lambda *_args: True,
    )
    first_store = _FailOnceAcceptedOutcomeStore(effects_path)
    first_handlers: list[ResearchArtifactBundleHandler] = []
    first_candidate = _CountingCandidateWorker()

    def first_handler_factory(**kwargs: Any) -> ResearchArtifactBundleHandler:
        handler = ResearchArtifactBundleHandler(**kwargs)
        first_handlers.append(handler)
        return handler

    first_runtime = _runtime(
        artifact_port=artifact_port,
        side_effect_store=first_store,
        event_port=event_port,
        artifact_handler_factory=first_handler_factory,
        llm_worker=first_candidate,
    )
    with pytest.raises(RuntimeError, match="accepted outcome persistence"):
        first_runtime.run(_request(run_id))

    manifest_path = artifact_root / run_id / "manifest.json"
    assert manifest_path.is_file()
    first_terminal_decision = next(
        decision
        for decision in first_store.list_decisions(run_id=run_id)
        if decision.origin is HarnessSideEffectOrigin.CONTROLLER_TERMINAL
    )
    assert first_store.get_outcome(
        effect_id=first_terminal_decision.effect_id,
        identity_scope_ref=first_terminal_decision.identity_scope_ref,
        subject_scope_ref=first_terminal_decision.subject_scope_ref,
        idempotency_key=first_terminal_decision.idempotency_key,
    ) is None
    assert first_handlers[0].commit_calls == 1
    worker_event_count_before_restart = sum(
        event.event_type is HarnessEventType.GRAPH_WORKER_RESULT_RECORDED
        for event in event_port.events
        if event.run_id == run_id
    )
    assert worker_event_count_before_restart > 0
    first_store.close()

    # Recompose every runtime-owned adapter while retaining only durable event
    # history, the manifest, and the side-effect database.
    second_store = SQLiteHarnessSideEffectStore(effects_path)
    second_handlers: list[ResearchArtifactBundleHandler] = []
    second_candidate = _CountingCandidateWorker(delegate=first_candidate.delegate)

    def second_handler_factory(**kwargs: Any) -> ResearchArtifactBundleHandler:
        handler = ResearchArtifactBundleHandler(**kwargs)
        second_handlers.append(handler)
        return handler

    second_runtime = _runtime(
        artifact_port=FilesystemHarnessArtifactPort(
            artifact_root,
            accepted_run_resolver=lambda *_args: True,
        ),
        side_effect_store=second_store,
        event_port=event_port,
        artifact_handler_factory=second_handler_factory,
        llm_worker=second_candidate,
    )
    try:
        recovered = second_runtime.run(_request(run_id))
    finally:
        second_store.close()

    assert recovered.succeeded is True
    assert second_candidate.calls == 0
    assert second_handlers[0].commit_calls == 1
    terminal_decisions = [
        decision
        for decision in second_store.list_decisions(run_id=run_id)
        if decision.origin is HarnessSideEffectOrigin.CONTROLLER_TERMINAL
    ]
    assert len(terminal_decisions) == 1
    assert terminal_decisions[0].effect_id == first_terminal_decision.effect_id
    outcome = second_store.get_outcome(
        effect_id=terminal_decisions[0].effect_id,
        identity_scope_ref=terminal_decisions[0].identity_scope_ref,
        subject_scope_ref=terminal_decisions[0].subject_scope_ref,
        idempotency_key=terminal_decisions[0].idempotency_key,
    )
    assert outcome is not None
    assert outcome.disposition is HarnessSideEffectDisposition.ACCEPTED
    assert outcome.effect_id == first_terminal_decision.effect_id
    assert sum(
        event.event_type is HarnessEventType.GRAPH_WORKER_RESULT_RECORDED
        for event in event_port.events
        if event.run_id == run_id
    ) == worker_event_count_before_restart
    manifest = second_runtime.artifact_port.read_terminal_manifest(run_id)
    assert manifest.publication is not None
    assert manifest.publication.terminal_side_effect_outcome_ref == outcome.checksum
    assert set(outcome.public_refs)


def test_terminal_member_failure_keeps_run_non_successful_and_public_refs_hidden(
    tmp_path: Path,
) -> None:
    run_id = "research-publication-terminal-member-failed"
    artifact_port = FilesystemHarnessArtifactPort(tmp_path / "artifacts")
    side_effect_store = SQLiteHarnessSideEffectStore(tmp_path / "effects.sqlite3")
    event_port = InMemoryHarnessEventPort()
    handlers: list[ResearchArtifactBundleHandler] = []

    def fail_third_terminal_member(
        index: int,
        _artifact_type: str,
        phase: str,
    ) -> None:
        if phase == "commit" and index == 3:
            raise RuntimeError("injected terminal member failure")

    def handler_factory(**kwargs: Any) -> ResearchArtifactBundleHandler:
        handler = ResearchArtifactBundleHandler(
            **kwargs,
            failure_injector=fail_third_terminal_member,
        )
        handlers.append(handler)
        return handler

    runtime = _runtime(
        artifact_port=artifact_port,
        side_effect_store=side_effect_store,
        event_port=event_port,
        artifact_handler_factory=handler_factory,
    )
    try:
        with pytest.raises(RuntimeError, match="terminal member failure"):
            runtime.run(_request(run_id))

        graph_state = event_port.recover_graph(run_id).state
        assert graph_state is not None
        assert graph_state.outcome is not RunOutcome.SUCCEEDED
        assert handlers[0].prepare_calls == 1
        assert handlers[0].commit_calls == 1
        terminal_decision = next(
            decision
            for decision in side_effect_store.list_decisions(run_id=run_id)
            if decision.origin is HarnessSideEffectOrigin.CONTROLLER_TERMINAL
        )
        assert side_effect_store.get_outcome(
            effect_id=terminal_decision.effect_id,
            identity_scope_ref=terminal_decision.identity_scope_ref,
            subject_scope_ref=terminal_decision.subject_scope_ref,
            idempotency_key=terminal_decision.idempotency_key,
        ) is None
    finally:
        side_effect_store.close()

    run_dir = artifact_port.root / run_id
    assert not (run_dir / "manifest.json").exists()
    assert not list((run_dir / "artifacts").glob("*.json"))
    assert list((run_dir / ".rc").rglob("*.json"))
    with pytest.raises(Exception):
        artifact_port.read_artifact(f"artifact://{run_id}/research-analysis")


def test_cleanup_failure_does_not_mask_terminal_graph_failure(
    tmp_path: Path,
) -> None:
    run_id = "research-publication-cleanup-secondary-failure"

    class _PrimaryFailureWorker(FakeResearchLLMWorker):
        def generate_candidate(
            self,
            *,
            task: str,
            payload: dict[str, Any],
        ) -> dict[str, Any]:
            del task, payload
            raise RuntimeError("primary-worker-failure")

    class _CleanupFailureHandler(ResearchArtifactBundleHandler):
        def cleanup_candidates(self, _run_id: str, **_kwargs: Any) -> tuple[str, ...]:
            raise OSError("secondary-cleanup-failure")

    artifact_port = FilesystemHarnessArtifactPort(tmp_path / "artifacts")
    side_effect_store = SQLiteHarnessSideEffectStore(tmp_path / "effects.sqlite3")
    runtime = _runtime(
        artifact_port=artifact_port,
        side_effect_store=side_effect_store,
        llm_worker=_PrimaryFailureWorker(),
        artifact_handler_factory=_CleanupFailureHandler,
    )
    try:
        result = runtime.run(_request(run_id))
    finally:
        side_effect_store.close()

    assert result.status == "failed"
    assert result.succeeded is False


def test_candidate_worker_registry_cannot_reach_commit_capabilities(
    tmp_path: Path,
) -> None:
    artifact_port = FilesystemHarnessArtifactPort(tmp_path / "artifacts")
    store = SQLiteHarnessSideEffectStore(tmp_path / "effects.sqlite3")
    runtime = _runtime(artifact_port=artifact_port, side_effect_store=store)
    workspace = _ResearchRunWorkspace(
        request=_request("research-publication-object-graph"),
        context_assembler=ContextAssembler(),
    )
    try:
        registry = runtime._worker_registry(workspace)
        assert set(registry) == {
            "load_paper_source",
            "compile_document",
            "run_research_rag",
            "build_evidence_pack",
            "analyze_structure",
            "analyze_contribution",
            "analyze_experiments",
            "verify_claims",
            "quality_gate",
            "build_reader_payload",
            "build_paper_card",
            "publish_artifacts",
        }
        reachable_by_worker = {
            worker_name: _reachable_objects(worker)
            for worker_name, worker in registry.items()
        }
    finally:
        store.close()

    for worker_name, reachable in reachable_by_worker.items():
        assert not any(item is artifact_port for item in reachable), worker_name
        assert not any(item is store for item in reachable), worker_name
        assert not any(item is runtime for item in reachable), worker_name
        assert ResearchArtifactBundleHandler not in reachable, worker_name
        assert not any(
            isinstance(
                item,
                (
                    FilesystemHarnessArtifactPort,
                    ResearchArtifactBundleHandler,
                    ResearchSinglePaperRuntime,
                    SQLiteHarnessSideEffectStore,
                ),
            )
            for item in reachable
        ), worker_name


@pytest.mark.parametrize("attempt", [1, 2, 3])
def test_publish_intent_uses_graph_activity_attempt(attempt: int) -> None:
    workspace = _ResearchRunWorkspace(
        request=_request(f"research-publication-attempt-{attempt}"),
        context_assembler=ContextAssembler(),
    )

    result = ResearchSinglePaperRuntime._publish_artifacts(
        {"harness_graph_activity": _graph_activity_task_context(attempt)},
        workspace,
    )

    assert result.effect_intent is not None
    assert result.effect_intent.attempt == attempt
    assert result.effect_intent.effect_id.endswith(
        result.effect_intent.atomic_group.rsplit(":", 1)[-1]
    )
    assert workspace.artifact_refs == {}
    assert workspace.planned_artifact_refs
    assert set(result.output["artifact_types"]) == set(
        workspace.planned_artifact_refs
    )
    assert all(
        ref.startswith(f"artifact://{workspace.request.run_id}/")
        for ref in workspace.planned_artifact_refs.values()
    )


def test_publish_intent_rejects_missing_graph_activity_identity() -> None:
    workspace = _ResearchRunWorkspace(
        request=_request("research-publication-missing-attempt"),
        context_assembler=ContextAssembler(),
    )

    with pytest.raises(Exception, match="Graph activity identity"):
        ResearchSinglePaperRuntime._publish_artifacts({}, workspace)


class _FailOnceAcceptedOutcomeStore(SQLiteHarnessSideEffectStore):
    def __init__(self, database: Path) -> None:
        super().__init__(database)
        self._failed_once = False

    def put_outcome(self, outcome):
        if (
            outcome.disposition is HarnessSideEffectDisposition.ACCEPTED
            and not self._failed_once
        ):
            self._failed_once = True
            raise RuntimeError("accepted outcome persistence failed once")
        return super().put_outcome(outcome)


class _CountingCandidateWorker:
    def __init__(self, *, delegate: FakeResearchLLMWorker | None = None) -> None:
        self.delegate = delegate or FakeResearchLLMWorker()
        self.calls = 0

    def generate_candidate(self, *, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        return self.delegate.generate_candidate(task=task, payload=payload)


def _runtime(
    *,
    artifact_port: FilesystemHarnessArtifactPort,
    side_effect_store: SQLiteHarnessSideEffectStore,
    event_port: InMemoryHarnessEventPort | None = None,
    artifact_handler_factory=ResearchArtifactBundleHandler,
    source_provider: Any | None = None,
    document_compiler: Any | None = None,
    llm_worker: Any | None = None,
    github_repository: Any | None = None,
    rag_runtime: Any | None = None,
) -> ResearchSinglePaperRuntime:
    return ResearchSinglePaperRuntime(
        source_provider=source_provider or FakeResearchSourceProvider(),
        document_compiler=document_compiler or FakeResearchDocumentCompiler(),
        llm_worker=llm_worker or FakeResearchLLMWorker(),
        github_repository=github_repository or FakeGithubRepositoryPort(),
        rag_runtime=rag_runtime or FakeResearchRAGRuntime(),
        artifact_port=artifact_port,
        event_port_factory=lambda _run_id: event_port or InMemoryHarnessEventPort(),
        side_effect_store=side_effect_store,
        artifact_handler_factory=artifact_handler_factory,
        node_output_resource_factory=in_memory_node_output_resource_factory,
    )


def _request(run_id: str) -> AnalyzePaperRequest:
    return AnalyzePaperRequest(
        run_id=run_id,
        paper_id="paper-harness-001",
        source_ref="https://arxiv.org/abs/2606.00123",
        user_id="user-publication",
        memory_namespace="research:user:user-publication",
    )


def _graph_activity_task_context(attempt: int) -> dict[str, Any]:
    graph_ref = HarnessGraphReference(
        graph_id="research.graph",
        schema_version=GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
        compiler_version=HARNESS_GRAPH_ONLY_COMPILER_VERSION,
        condition_policy_version=HARNESS_CONDITION_POLICY_VERSION,
        checksum=checksum_for({"graph": "research.graph", "version": "2"}),
        graph_ref=HarnessContractReference(HarnessContractKind.GRAPH, "research.graph", "2"),
    )
    activity = HarnessGraphActivity(
        run_id="research-publication-attempt",
        graph_ref=graph_ref,
        node_id="publish_artifacts",
        node_instance_id=f"publish_artifacts:{attempt}",
        step_ref=HarnessContractReference(HarnessContractKind.STEP, "publish_artifacts", "1"),
        worker_ref=HarnessContractReference(HarnessContractKind.WORKER, "research.publish-artifacts", "1"),
        activity_ref=HarnessContractReference(HarnessContractKind.ACTIVITY, "harness.publish-artifacts", "1"),
        attempt=attempt,
        input_ref=checksum_for({"run_id": "research-publication-attempt"}),
        causal_decision_checksum=checksum_for({"decision": "publish"}),
        causal_decision_sequence=attempt,
        fencing_generation=1,
    )
    return HarnessGraphActivityTaskContext(
        activity=activity,
        graph_checkpoint_ref=f"checkpoint://research-publication-attempt/{attempt}",
    ).to_dict()


def _reachable_objects(root: Any) -> tuple[Any, ...]:
    seen_ids: set[int] = set()
    found: dict[int, Any] = {}

    def visit(value: Any) -> None:
        identity = id(value)
        if identity in seen_ids:
            return
        seen_ids.add(identity)
        found[identity] = value
        if isinstance(value, (type, ModuleType)):
            return
        if isinstance(value, FunctionType):
            for cell in value.__closure__ or ():
                visit(cell.cell_contents)
            for item in value.__defaults__ or ():
                visit(item)
            for item in (value.__kwdefaults__ or {}).values():
                visit(item)
            return
        if isinstance(value, MethodType):
            visit(value.__self__)
            visit(value.__func__)
            return
        if isinstance(value, partial):
            visit(value.func)
            for item in value.args:
                visit(item)
            for key, item in (value.keywords or {}).items():
                visit(key)
                visit(item)
            return
        if isinstance(value, (dict, MappingProxyType)):
            for key, item in value.items():
                visit(key)
                visit(item)
            return
        if isinstance(value, (list, tuple, set, frozenset)):
            for item in value:
                visit(item)
            return
        if is_dataclass(value):
            for field_info in fields(value):
                visit(getattr(value, field_info.name))
            return
        try:
            attributes = vars(value)
        except TypeError:
            return
        for item in attributes.values():
            visit(item)

    visit(root)
    return tuple(found.values())
