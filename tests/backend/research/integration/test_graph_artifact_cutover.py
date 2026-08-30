from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

from backend.research.application.artifact_context import (
    ResearchGraphArtifactContextProvider,
)
from backend.research.application.graph_result_committer import (
    RESEARCH_NODE_RESULT_POLICIES,
    ResearchGraphResultCommitter,
)
from backend.research.application.graph_artifact_governance import (
    ResearchGraphArtifactGovernanceService,
)
from backend.research.application.single_paper_runtime import (
    AnalyzePaperRequest,
    ResearchSinglePaperRuntime,
)
from backend.research.domain import research_event_tenant_id
from framework.events.canonical import checksum_for
from framework.harness import (
    ContextAssembler,
    HarnessEventType,
    HarnessGraphControlPlaneRuntime,
    HarnessGraphResultRuntime,
    HarnessWorkerResult,
    HarnessWorkerStatus,
)
from framework.harness.artifacts import (
    GraphArtifactGovernanceRuntime,
    GraphArtifactQuotaScope,
)
from framework.harness.runtime import (
    GraphArtifactPersistenceConfig,
    GraphArtifactRolloutMode,
    PersistencePolicy,
    ResultMaterializer,
)
from infrastructure.research.artifact_port import FilesystemHarnessArtifactPort
from infrastructure.research.graph_artifact_lifecycle import (
    FilesystemGraphArtifactLifecycle,
)
from infrastructure.research.artifact_publication import (
    ResearchArtifactBundleHandler,
)
from infrastructure.storage.artifacts import (
    LocalJsonArtifactCatalog,
    SQLiteGraphResultStore,
)
from infrastructure.storage.events import (
    DurableEventStorage,
    durable_event_storage_from_env,
)
from infrastructure.storage.harness import SQLiteHarnessNodeOutputResource
from infrastructure.storage.harness import SQLiteHarnessSideEffectStore
from tests.backend.research.fakes import (
    FakeGithubRepositoryPort,
    FakeResearchDocumentCompiler,
    FakeResearchLLMWorker,
    FakeResearchRAGRuntime,
    FakeResearchSourceProvider,
)


_ACCEPTED_CHAIN = frozenset(
    set(RESEARCH_NODE_RESULT_POLICIES).difference({"dynamic_analysis_stage"})
)
_GATE_FAILED_CHAIN = frozenset(
    {
        "load_paper_source",
        "compile_document",
        "run_research_rag",
        "build_evidence_pack",
        "analyze_structure",
        "analyze_contribution",
        "analyze_experiments",
        "verify_claims",
        "quality_gate",
    }
)


def test_enforced_source_to_report_reopens_without_external_producers(
    tmp_path: Path,
) -> None:
    request = _request("research-graph-artifact-accepted")
    artifact_root = tmp_path / "artifacts"
    encryption_key = Fernet.generate_key().decode("ascii")
    producers = _counting_producers()
    first = _runtime_bundle(
        artifact_root=artifact_root,
        encryption_key=encryption_key,
        producers=producers,
    )
    try:
        result = first.runtime.run(request)
        first_port = _event_port(first.event_storage, request)
        first_recovery = first_port.recover_graph(request.run_id)
        first_history = first_port.read_history(request.run_id)
        first_worker_event_count = sum(
            event.event_type is HarnessEventType.GRAPH_WORKER_RESULT_RECORDED
            for event in first_history
        )
        first_lineage = _lineage_checksums(first_recovery.activity_result_commits)
    finally:
        first.side_effect_store.close()

    assert result.succeeded is True
    assert set(first_lineage) == _ACCEPTED_CHAIN
    assert first_recovery.state is not None
    assert first_recovery.state.outcome.value == "succeeded"
    assert first_worker_event_count == len(_ACCEPTED_CHAIN)
    assert set(producers.source.calls) == {"fetch_paper", "fetch_source_record"}
    assert producers.document.calls == ["compile"]
    assert producers.rag.calls == ["run"]
    assert producers.llm.calls
    assert producers.github.calls

    for commit in first_recovery.activity_result_commits:
        lineage = commit.result.result_lineage
        assert lineage is not None
        assert lineage.artifact_refs
        for artifact_ref in lineage.artifact_refs:
            stored = first.artifact_port.read_graph_result_artifact(
                artifact_ref.ref,
                expected_run_id=artifact_ref.run_id,
            )
            assert (
                stored["payload"]["candidate_checksum"]
                == artifact_ref.content_checksum
            )

    manifest = first.artifact_port.read_terminal_manifest(request.run_id)
    assert manifest.status == "succeeded"
    assert manifest.publication is not None
    assert manifest.publication.publication_authority_ref == result.diagnostics[
        "publication_authority_ref"
    ]
    assert all(
        not artifact_type.startswith("graph-result-")
        for artifact_type in result.artifact_refs
    )

    forbidden = _forbidden_producers()
    reopened = _runtime_bundle(
        artifact_root=artifact_root,
        encryption_key=encryption_key,
        producers=forbidden,
    )
    try:
        replayed = reopened.runtime.run(request)
        reopened_port = _event_port(reopened.event_storage, request)
        replay_recovery = reopened_port.recover_graph(request.run_id)
        replay_history = reopened_port.read_history(request.run_id)
    finally:
        reopened.side_effect_store.close()

    assert replayed.succeeded is True
    assert replayed.diagnostics["recovered_from_durable_publication"] is True
    assert all(not producer.calls for producer in forbidden.all())
    assert _lineage_checksums(
        replay_recovery.activity_result_commits
    ) == first_lineage
    assert replay_recovery.state is not None
    assert replay_recovery.state.projection_checksum == (
        first_recovery.state.projection_checksum
    )
    assert sum(
        event.event_type is HarnessEventType.GRAPH_WORKER_RESULT_RECORDED
        for event in replay_history
    ) == first_worker_event_count


def test_enforced_quality_gate_failure_retains_internal_results_without_publication(
    tmp_path: Path,
) -> None:
    request = replace(
        _request("research-graph-artifact-gate-failed"),
        options={"max_replans": 0},
    )
    bundle = _runtime_bundle(
        artifact_root=tmp_path / "artifacts",
        encryption_key=Fernet.generate_key().decode("ascii"),
        producers=_counting_producers(),
        runtime_type=_QualityGateFailingRuntime,
    )
    try:
        result = bundle.runtime.run(request)
        port = _event_port(bundle.event_storage, request)
        recovery = port.recover_graph(request.run_id)
        history = port.read_history(request.run_id)
        decisions = bundle.side_effect_store.list_decisions(run_id=request.run_id)
    finally:
        bundle.side_effect_store.close()

    assert result.status == "halted"
    assert result.artifact_refs == {}
    assert decisions == ()
    assert recovery.state is not None
    assert recovery.state.lifecycle.value == "halted"
    assert recovery.state.outcome.value == "none"

    lineages = {
        commit.result.result_lineage.node_id: commit.result.result_lineage
        for commit in recovery.activity_result_commits
        if commit.result.result_lineage is not None
    }
    assert set(lineages) == _GATE_FAILED_CHAIN
    assert "publish_artifacts" not in lineages
    assert all(
        artifact_ref.artifact_class != "report"
        for lineage in lineages.values()
        for artifact_ref in lineage.artifact_refs
    )

    evidence_lineage = lineages["build_evidence_pack"]
    evidence_ref = evidence_lineage.artifact_refs[0]
    evidence = bundle.artifact_port.read_graph_result_artifact(
        evidence_ref.ref,
        expected_run_id=evidence_ref.run_id,
    )
    assert evidence["payload"]["candidate_checksum"] == evidence_ref.content_checksum

    quality_lineage = lineages["quality_gate"]
    assert quality_lineage.artifact_refs
    assert all(
        artifact_ref.artifact_class == "evidence"
        and artifact_ref.required_for_publication is False
        for artifact_ref in quality_lineage.artifact_refs
    )

    quality_failures = [
        event
        for event in history
        if event.event_type is HarnessEventType.GATE_EVALUATED
        and event.node_id == "quality_gate"
        and event.payload.get("passed") is False
    ]
    assert len(quality_failures) == 1
    gate_observations = [
        commit.observation
        for commit in recovery.observation_commits
        if commit.observation.node_id == "quality_gate"
        and commit.observation.observation_type.value == "gate_result"
        and commit.observation.payload.get("passed") is False
    ]
    assert len(gate_observations) == 1
    gate_observation = gate_observations[0]
    assert gate_observation.contract_ref.exact_ref == "ResearchQualityGate@1"
    assert gate_observation.payload["input_ref"].startswith("sha256:")
    assert gate_observation.payload["result_ref"].startswith("sha256:")

    manifest = bundle.artifact_port.read_terminal_manifest(request.run_id)
    assert manifest.publication is None


def test_enforced_accepted_and_gate_failed_runs_produce_reproducible_cost_report(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "artifacts"
    encryption_key = Fernet.generate_key().decode("ascii")
    accepted_request = _request("research-governance-accepted")
    accepted_bundle = _runtime_bundle(
        artifact_root=artifact_root,
        encryption_key=encryption_key,
        producers=_counting_producers(),
    )
    try:
        accepted = accepted_bundle.runtime.run(accepted_request)
    finally:
        accepted_bundle.side_effect_store.close()

    failed_request = replace(
        _request("research-governance-gate-failed"),
        options={"max_replans": 0},
    )
    failed_bundle = _runtime_bundle(
        artifact_root=artifact_root,
        encryption_key=encryption_key,
        producers=_counting_producers(),
        runtime_type=_QualityGateFailingRuntime,
    )
    try:
        failed = failed_bundle.runtime.run(failed_request)
    finally:
        failed_bundle.side_effect_store.close()

    tenant_id = research_event_tenant_id(_actor_metadata(accepted_request))
    all_facts = failed_bundle.result_store.list_usage(
        tenant_id=tenant_id,
        window_start=datetime.min.replace(tzinfo=timezone.utc),
        window_end=datetime.max.replace(tzinfo=timezone.utc),
    )
    assert all_facts
    day_start = min(fact.occurred_at for fact in all_facts).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    day_end = day_start + timedelta(days=1)
    day_facts = tuple(
        fact for fact in all_facts if day_start <= fact.occurred_at < day_end
    )
    quota = failed_bundle.result_store.quota_snapshots(
        tenant_id=tenant_id,
        captured_at=day_end,
    )
    tenant_quota = next(
        item for item in quota if item.scope is GraphArtifactQuotaScope.TENANT
    )
    accepted_claims = failed_bundle.catalog.list_claims_by_run(
        tenant_id=tenant_id,
        run_id=accepted_request.run_id,
    )
    failed_claims = failed_bundle.catalog.list_claims_by_run(
        tenant_id=tenant_id,
        run_id=failed_request.run_id,
    )

    first_report = failed_bundle.governance_service.generate_cost_report(
        tenant_id=tenant_id,
        day=day_start.date(),
        generated_at=day_end + timedelta(seconds=1),
    )
    repeated_report = failed_bundle.governance_service.generate_cost_report(
        tenant_id=tenant_id,
        day=day_start.date(),
        generated_at=day_end + timedelta(minutes=1),
    )
    global_aggregate = next(
        aggregate
        for aggregate in first_report.aggregates
        if aggregate.dimension.run_id is None
        and aggregate.dimension.graph_id is None
        and aggregate.dimension.node_id is None
        and aggregate.dimension.artifact_class is None
    )

    assert accepted.succeeded is True
    assert failed.status == "halted"
    assert accepted_claims
    assert failed_claims
    assert tenant_quota.charged_bytes > 0
    assert tenant_quota.charged_objects > 0
    assert tenant_quota.pending_bytes == 0
    assert tenant_quota.pending_objects == 0
    assert day_facts
    assert first_report == repeated_report
    assert first_report.provisional is False
    assert first_report.usage_watermark == (
        failed_bundle.result_store.usage_watermark(tenant_id=tenant_id)
    )
    assert global_aggregate.logical_bytes > 0
    assert global_aggregate.logical_count >= len(accepted_claims) + len(failed_claims)
    assert global_aggregate.unique_physical_bytes > 0


@dataclass(frozen=True)
class _ProducerSet:
    source: Any
    document: Any
    llm: Any
    github: Any
    rag: Any

    def all(self) -> tuple[Any, ...]:
        return (self.source, self.document, self.llm, self.github, self.rag)


class _CountingProducer:
    def __init__(self, delegate: Any) -> None:
        self.delegate = delegate
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Any:
        value = getattr(self.delegate, name)
        if not callable(value):
            return value

        def invoke(*args: Any, **kwargs: Any) -> Any:
            self.calls.append(name)
            return value(*args, **kwargs)

        return invoke


class _ForbiddenProducer:
    def __init__(self, label: str) -> None:
        self.label = label
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Any:
        def invoke(*_args: Any, **_kwargs: Any) -> Any:
            self.calls.append(name)
            raise AssertionError(
                f"durable Research replay invoked {self.label}.{name}"
            )

        return invoke


def _counting_producers() -> _ProducerSet:
    return _ProducerSet(
        source=_CountingProducer(FakeResearchSourceProvider()),
        document=_CountingProducer(FakeResearchDocumentCompiler()),
        llm=_CountingProducer(FakeResearchLLMWorker()),
        github=_CountingProducer(FakeGithubRepositoryPort()),
        rag=_CountingProducer(FakeResearchRAGRuntime()),
    )


def _forbidden_producers() -> _ProducerSet:
    return _ProducerSet(
        source=_ForbiddenProducer("source"),
        document=_ForbiddenProducer("document"),
        llm=_ForbiddenProducer("llm"),
        github=_ForbiddenProducer("github"),
        rag=_ForbiddenProducer("rag"),
    )


@dataclass(frozen=True)
class _RuntimeBundle:
    runtime: ResearchSinglePaperRuntime
    event_storage: DurableEventStorage
    artifact_port: FilesystemHarnessArtifactPort
    side_effect_store: SQLiteHarnessSideEffectStore
    catalog: LocalJsonArtifactCatalog
    result_store: SQLiteGraphResultStore
    governance_service: ResearchGraphArtifactGovernanceService


def _runtime_bundle(
    *,
    artifact_root: Path,
    encryption_key: str,
    producers: _ProducerSet,
    runtime_type: type[ResearchSinglePaperRuntime] = ResearchSinglePaperRuntime,
) -> _RuntimeBundle:
    records_root = artifact_root / "_records"
    event_storage = durable_event_storage_from_env(
        artifact_root=artifact_root,
        env={"NEWS_ACTIVITY_ENCRYPTION_KEY": encryption_key},
    )
    artifact_port = FilesystemHarnessArtifactPort(
        artifact_root,
        accepted_run_resolver=lambda *_args: True,
    )
    config = GraphArtifactPersistenceConfig(
        mode=GraphArtifactRolloutMode.ENFORCE,
    )
    catalog = LocalJsonArtifactCatalog(records_root / "graph_artifact_catalog")
    result_store = SQLiteGraphResultStore(
        records_root / "graph-results.sqlite3",
        max_materialized_bytes_per_run=config.max_materialized_bytes_per_run,
        max_artifacts_per_run=config.max_artifacts_per_run,
    )
    materializer = ResultMaterializer(
        policy=PersistencePolicy(config),
        artifact_port=artifact_port,
        catalog=catalog,
        quota=result_store,
        usage=result_store,
        cache=result_store,
        attempts=result_store,
    )
    governance_service = ResearchGraphArtifactGovernanceService(
        GraphArtifactGovernanceRuntime(
            catalog=catalog,
            lifecycle=FilesystemGraphArtifactLifecycle(
                artifact_root,
                artifact_port=artifact_port,
            ),
            ledger=result_store,
            config=config,
        )
    )
    side_effect_store = SQLiteHarnessSideEffectStore(
        records_root / "side-effects.sqlite3"
    )

    def scoped_event_port_factory(
        _run_id: str,
        actor_metadata: dict[str, Any],
    ):
        return event_storage.create_harness_transition_port(
            tenant_id=research_event_tenant_id(actor_metadata)
        )

    def context_assembler_factory(_run_id: str, event_port) -> ContextAssembler:
        return ContextAssembler(
            artifact_context_provider=ResearchGraphArtifactContextProvider(
                event_port=event_port,
                catalog=catalog,
                reader=artifact_port,
                usage=result_store,
                config=config,
            )
        )

    def graph_result_committer_factory(
        *,
        event_port,
        request: AnalyzePaperRequest,
        workspace,
    ) -> ResearchGraphResultCommitter:
        tenant_id = research_event_tenant_id(_actor_metadata(request))
        return ResearchGraphResultCommitter(
            materializer=materializer,
            graph_result_runtime=HarnessGraphResultRuntime(
                HarnessGraphControlPlaneRuntime(event_port)
            ),
            config=config,
            tenant_id=tenant_id,
            tenant_scope_ref=checksum_for(tenant_id),
            context_fingerprint_resolver=lambda node_id: (
                _context_fingerprint(workspace)
                if node_id == "publish_artifacts"
                else None
            ),
        )

    runtime = runtime_type(
        source_provider=producers.source,
        document_compiler=producers.document,
        llm_worker=producers.llm,
        github_repository=producers.github,
        rag_runtime=producers.rag,
        artifact_port=artifact_port,
        event_port_factory=lambda _run_id: (_ for _ in ()).throw(
            AssertionError("unscoped Research event port was used")
        ),
        scoped_event_port_factory=scoped_event_port_factory,
        context_assembler_factory=context_assembler_factory,
        side_effect_store=side_effect_store,
        artifact_handler_factory=ResearchArtifactBundleHandler,
        graph_result_committer_factory=graph_result_committer_factory,
        node_output_resource_factory=lambda _run_id: SQLiteHarnessNodeOutputResource(
            records_root / "node-output.sqlite3"
        ),
    )
    return _RuntimeBundle(
        runtime=runtime,
        event_storage=event_storage,
        artifact_port=artifact_port,
        side_effect_store=side_effect_store,
        catalog=catalog,
        result_store=result_store,
        governance_service=governance_service,
    )


class _QualityGateFailingRuntime(ResearchSinglePaperRuntime):
    def _worker_registry(self, workspace):
        registry = super()._worker_registry(workspace)
        quality_worker = registry["quality_gate"]

        def fail_quality_gate(task: dict[str, Any]) -> HarnessWorkerResult:
            result = quality_worker(task)
            assert result.status is HarnessWorkerStatus.SUCCEEDED
            output = deepcopy(result.output)
            output["research_quality"]["score"] = 0.5
            return replace(result, output=output)

        registry["quality_gate"] = fail_quality_gate
        return registry


def _request(run_id: str) -> AnalyzePaperRequest:
    return AnalyzePaperRequest(
        run_id=run_id,
        paper_id="paper-harness-001",
        source_ref="https://arxiv.org/abs/2606.00123",
        tenant_id="tenant-graph-artifact",
        user_id="user-graph-artifact",
        memory_namespace=(
            "research:tenant:tenant-graph-artifact:user:user-graph-artifact"
        ),
    )


def _actor_metadata(request: AnalyzePaperRequest) -> dict[str, str]:
    metadata = {"memory_namespace": str(request.memory_namespace)}
    if request.tenant_id:
        metadata["tenant_id"] = request.tenant_id
    if request.user_id:
        metadata["user_id"] = request.user_id
    return metadata


def _event_port(
    event_storage: DurableEventStorage,
    request: AnalyzePaperRequest,
):
    return event_storage.create_harness_transition_port(
        tenant_id=research_event_tenant_id(_actor_metadata(request))
    )


def _context_fingerprint(workspace) -> str:
    envelope = workspace.context_envelope
    assert envelope is not None
    fingerprint = envelope.metadata.get("artifact_context_fingerprint")
    assert isinstance(fingerprint, str) and fingerprint.startswith("sha256:")
    return fingerprint


def _lineage_checksums(commits) -> dict[str, str]:
    lineages = (
        commit.result.result_lineage
        for commit in commits
        if commit.result.result_lineage is not None
    )
    return {
        lineage.node_id: lineage.lineage_checksum
        for lineage in lineages
    }
