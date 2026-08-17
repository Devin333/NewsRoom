from __future__ import annotations

from datetime import UTC, datetime

import pytest

from business.research.application.graph_result_committer import (
    RESEARCH_NODE_RESULT_POLICIES,
    ResearchGraphResultCommitter,
    ResearchGraphResultRequestFactory,
    ResearchGraphResultShadowObserver,
)
from business.research.workflows.paper_analysis_workflow import (
    build_dynamic_paper_analysis_workflow_spec,
    build_paper_analysis_workflow_spec,
)
from framework.events.canonical import checksum_for
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.event import HarnessEventType
from framework.harness.control_plane.graph_application import (
    HarnessGraphControlPlaneRuntime,
)
from framework.harness.control_plane.harness import (
    HarnessControlPlane,
    InMemoryHarnessEventPort,
)
from framework.harness.control_plane.state import HarnessRunSpec
from framework.harness.runtime import (
    ArtifactClass,
    ContextPolicy,
    GraphArtifactPersistenceConfig,
    GraphArtifactResultError,
    GraphArtifactResultErrorCode,
    GraphArtifactRolloutMode,
    HarnessGraphResultRuntime,
    RetentionClass,
)
from framework.harness.workflow.compiler import HarnessWorkflowGraphCompiler
from framework.harness.graph.dsl import HarnessGraphSpec, StepRef
from framework.harness.graph.model import HarnessExecutableNode
from framework.harness.workflow.spec import HarnessWorkflowSpec
from framework.harness.graph.activity import HarnessStepSpec
from framework.harness.workers.result import HarnessWorkerResult
from framework.shared.json import stable_json_dumps
from tests.framework.harness.runtime.test_graph_result_runtime import (
    FailResultProjectionPort,
)
from tests.framework.harness.runtime.test_materializer import (
    RecordingArtifactPort,
    RecordingAttempts,
    RecordingCache,
    RecordingCatalog,
    RecordingQuota,
    _materializer,
)


NOW = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
TENANT_ID = "research-scope:sha256:" + "1" * 64
TENANT_SCOPE_REF = checksum_for(TENANT_ID)
SUBJECT_SCOPE_REF = checksum_for("paper-graph-result")


@pytest.mark.parametrize(
    ("node_id", "artifact_class", "retention_class", "context_policy"),
    (
        (
            "load_paper_source",
            ArtifactClass.EVIDENCE,
            RetentionClass.EVIDENCE,
            ContextPolicy.REF_LOAD_ALLOWED,
        ),
        (
            "compile_document",
            ArtifactClass.EVIDENCE,
            RetentionClass.EVIDENCE,
            ContextPolicy.REF_LOAD_ALLOWED,
        ),
        (
            "build_evidence_pack",
            ArtifactClass.EVIDENCE,
            RetentionClass.EVIDENCE,
            ContextPolicy.REF_LOAD_ALLOWED,
        ),
        (
            "verify_claims",
            ArtifactClass.EVIDENCE,
            RetentionClass.EVIDENCE,
            ContextPolicy.REF_LOAD_ALLOWED,
        ),
        (
            "quality_gate",
            ArtifactClass.EVIDENCE,
            RetentionClass.EVIDENCE,
            ContextPolicy.REF_LOAD_ALLOWED,
        ),
        (
            "run_research_rag",
            ArtifactClass.INTERMEDIATE,
            RetentionClass.RUN,
            ContextPolicy.SUMMARY_ONLY,
        ),
        (
            "analyze_structure",
            ArtifactClass.INTERMEDIATE,
            RetentionClass.RUN,
            ContextPolicy.SUMMARY_ONLY,
        ),
        (
            "analyze_contribution",
            ArtifactClass.INTERMEDIATE,
            RetentionClass.RUN,
            ContextPolicy.SUMMARY_ONLY,
        ),
        (
            "analyze_experiments",
            ArtifactClass.INTERMEDIATE,
            RetentionClass.RUN,
            ContextPolicy.SUMMARY_ONLY,
        ),
        (
            "dynamic_analysis_stage",
            ArtifactClass.INTERMEDIATE,
            RetentionClass.RUN,
            ContextPolicy.SUMMARY_ONLY,
        ),
        (
            "build_reader_payload",
            ArtifactClass.INTERMEDIATE,
            RetentionClass.RUN,
            ContextPolicy.SUMMARY_ONLY,
        ),
        (
            "build_paper_card",
            ArtifactClass.INTERMEDIATE,
            RetentionClass.RUN,
            ContextPolicy.SUMMARY_ONLY,
        ),
        (
            "publish_artifacts",
            ArtifactClass.REPORT,
            RetentionClass.REPORT,
            ContextPolicy.REF_LOAD_ALLOWED,
        ),
    ),
)
def test_research_node_policy_inventory_is_complete_and_trusted(
    node_id: str,
    artifact_class: ArtifactClass,
    retention_class: RetentionClass,
    context_policy: ContextPolicy,
) -> None:
    policy = RESEARCH_NODE_RESULT_POLICIES[node_id]

    assert policy.artifact_class is artifact_class
    assert policy.retention_class is retention_class
    assert policy.context_policy is context_policy
    assert policy.required_for_publication is (node_id == "publish_artifacts")


def test_research_node_policy_inventory_matches_compiled_graphs() -> None:
    compiler = HarnessWorkflowGraphCompiler()
    graphs = tuple(
        compiler.compile(builder()).graph
        for builder in (
            build_paper_analysis_workflow_spec,
            build_dynamic_paper_analysis_workflow_spec,
        )
    )
    request_factory = ResearchGraphResultRequestFactory()

    for graph in graphs:
        request_factory.validate_graph(graph)

    executable_node_ids = {
        node.node_id
        for graph in graphs
        for node in graph.nodes
        if isinstance(node, HarnessExecutableNode)
    }
    assert set(request_factory.policies) == executable_node_ids


def test_large_evidence_candidate_is_materialized_and_graph_state_is_bounded() -> None:
    raw_evidence = "evidence-body-" + "x" * 70_000
    worker_result = HarnessWorkerResult(
        "succeeded",
        output={"evidence_pack": {"content": raw_evidence}},
    )
    fixture = _run(
        node_id="build_evidence_pack",
        worker_result=worker_result,
    )

    envelope = fixture.envelope
    lineage = fixture.lineage
    stored = fixture.artifact.read_artifact(
        envelope.materialized_refs[0].ref
    )["payload"]["value"]
    state = fixture.port.recover_graph(fixture.run_id).state
    assert state is not None
    graph_json = stable_json_dumps(state.to_dict())

    assert envelope.persistence_decision.artifact_class is ArtifactClass.EVIDENCE
    assert envelope.persistence_decision.retention_class is RetentionClass.EVIDENCE
    assert envelope.persistence_decision.required is True
    assert (
        stored["worker_candidate"]["worker_result"]["output"]
        ["evidence_pack"]["content"]
        == raw_evidence
    )
    assert lineage.artifact_refs[0].artifact_class == "evidence"
    assert lineage.inline_projection == {
        "candidate_artifact_count": 0,
        "candidate_evidence_count": 0,
        "has_diagnostics": False,
        "has_error": False,
        "worker_candidate_ref": worker_result.candidate_result_ref,
        "worker_status": "succeeded",
    }
    assert raw_evidence not in graph_json
    assert len(graph_json) < 40_000
    assert fixture.catalog.requests[0].record == envelope.materialized_refs[0]

    much_larger_evidence = "evidence-body-" + "y" * 700_000
    much_larger = _run(
        node_id="build_evidence_pack",
        worker_result=HarnessWorkerResult(
            "succeeded",
            output={"evidence_pack": {"content": much_larger_evidence}},
        ),
    )
    much_larger_state = much_larger.port.recover_graph(much_larger.run_id).state
    assert much_larger_state is not None
    much_larger_graph_json = stable_json_dumps(much_larger_state.to_dict())

    assert much_larger_evidence not in much_larger_graph_json
    assert len(much_larger_graph_json) < 40_000
    assert abs(len(much_larger_graph_json) - len(graph_json)) < 256


def test_report_candidate_is_durable_without_publication_projection() -> None:
    fixture = _run(
        node_id="publish_artifacts",
        worker_result=HarnessWorkerResult(
            "succeeded",
            output={
                "artifact_bundle_ref": checksum_for("research-report-bundle"),
                "artifact_types": ["research-analysis", "research-paper-card"],
            },
        ),
    )

    envelope = fixture.envelope
    lineage = fixture.lineage

    assert envelope.persistence_decision.artifact_class is ArtifactClass.REPORT
    assert envelope.persistence_decision.retention_class is RetentionClass.REPORT
    assert envelope.persistence_decision.required is True
    assert envelope.materialized_refs[0].required_for_publication is True
    assert lineage.artifact_refs[0].required_for_publication is True
    assert "publication" not in lineage.inline_projection
    assert "public_refs" not in lineage.inline_projection


def test_failed_quality_gate_retains_diagnostics_without_publication_refs() -> None:
    failure = {
        "gate": "research_quality",
        "reason_code": "evidence_coverage_below_threshold",
    }
    fixture = _run(
        node_id="quality_gate",
        worker_result=HarnessWorkerResult(
            "failed",
            diagnostics={"gate_failures": [failure]},
            error="deterministic quality gate failed",
        ),
    )

    envelope = fixture.envelope
    lineage = fixture.lineage
    stored = fixture.artifact.read_artifact(
        envelope.materialized_refs[0].ref
    )["payload"]["value"]

    assert envelope.status.value == "failed"
    assert envelope.persistence_decision.artifact_class is ArtifactClass.EVIDENCE
    assert stored["worker_candidate"]["worker_result"]["diagnostics"] == {
        "gate_failures": [failure]
    }
    assert lineage.inline_projection["has_diagnostics"] is True
    assert lineage.inline_projection["has_error"] is True
    assert lineage.inline_projection["worker_status"] == "failed"
    assert all(not item.required_for_publication for item in lineage.artifact_refs)
    assert "public_refs" not in lineage.inline_projection


def test_shadow_records_policy_evidence_without_writing_or_claiming_lineage() -> None:
    fixture = _fixture(node_id="build_evidence_pack")
    shadow_config = GraphArtifactPersistenceConfig(
        mode=GraphArtifactRolloutMode.SHADOW
    )
    observer = ResearchGraphResultShadowObserver(
        graph_result_runtime=HarnessGraphResultRuntime(
            HarnessGraphControlPlaneRuntime(fixture.port)
        ),
        event_port=fixture.port,
        config=shadow_config,
        tenant_id=TENANT_ID,
        tenant_scope_ref=TENANT_SCOPE_REF,
    )
    raw_evidence = "shadow-evidence-" + "x" * 70_000

    result = HarnessControlPlane(
        event_port=fixture.port,
        worker_registry={
            fixture.node_id: lambda _task: HarnessWorkerResult(
                "succeeded",
                output={"evidence_pack": {"content": raw_evidence}},
            )
        },
        graph_result_observer=observer,
    ).run(fixture.run_spec)

    decisions = [
        event
        for event in fixture.port.events
        if event.event_type is HarnessEventType.DECISION_RECORDED
        and event.payload.get("decision_type") == "evaluate_result_persistence"
    ]
    recovery = fixture.port.recover_graph(fixture.run_id)
    assert result.succeeded is True
    assert len(decisions) == 1
    evidence = decisions[0].payload["payload"]
    assert evidence["rollout_mode"] == "shadow"
    assert evidence["persistence_mode"] == "artifact"
    assert evidence["legacy_payload_ref"].startswith("sha256:")
    assert raw_evidence not in stable_json_dumps(decisions[0].payload)
    assert fixture.artifact.write_count == 0
    assert fixture.attempts.put_count == 0
    assert recovery.activity_result_commits[0].result.result_lineage is None


def test_read_only_reuses_existing_research_attempt_without_writes() -> None:
    worker_result = HarnessWorkerResult(
        "succeeded",
        output={"evidence_pack": {"content": "x" * 70_000}},
    )
    fixture = _run(node_id="build_evidence_pack", worker_result=worker_result)
    recovery = fixture.port.recover_graph(fixture.run_id)
    assert recovery.graph is not None
    assert recovery.run_spec_checksum is not None
    activity = recovery.activities[0]
    first = fixture.envelope
    before = (
        fixture.artifact.write_count,
        fixture.attempts.put_count,
        len(fixture.catalog.requests),
    )
    read_only = ResearchGraphResultCommitter(
        materializer=_materializer(
            artifact=fixture.artifact,
            attempts=fixture.attempts,
            cache=RecordingCache(),
            catalog=fixture.catalog,
            quota=RecordingQuota(),
            config=GraphArtifactPersistenceConfig(
                mode=GraphArtifactRolloutMode.READ_ONLY
            ),
        ),
        graph_result_runtime=HarnessGraphResultRuntime(
            HarnessGraphControlPlaneRuntime(fixture.port)
        ),
        config=GraphArtifactPersistenceConfig(
            mode=GraphArtifactRolloutMode.READ_ONLY
        ),
        tenant_id=TENANT_ID,
        tenant_scope_ref=TENANT_SCOPE_REF,
    )

    state = read_only.commit_result(
        activity=activity,
        graph=recovery.graph,
        run_spec_checksum=recovery.run_spec_checksum,
        worker_result=worker_result,
        occurred_at=first.created_at,
    )

    assert state.outcome.value == "succeeded"
    assert fixture.attempts.get(first.binding) == first
    assert (
        fixture.artifact.write_count,
        fixture.attempts.put_count,
        len(fixture.catalog.requests),
    ) == before


def test_read_only_missing_attempt_fails_before_graph_mutation() -> None:
    worker_result = HarnessWorkerResult(
        "succeeded",
        output={"evidence_pack": {"content": "x" * 70_000}},
    )
    fixture = _run(node_id="build_evidence_pack", worker_result=worker_result)
    recovery = fixture.port.recover_graph(fixture.run_id)
    assert recovery.graph is not None
    assert recovery.run_spec_checksum is not None
    empty_attempts = RecordingAttempts()
    read_only = ResearchGraphResultCommitter(
        materializer=_materializer(
            artifact=fixture.artifact,
            attempts=empty_attempts,
            cache=RecordingCache(),
            catalog=fixture.catalog,
            quota=RecordingQuota(),
            config=GraphArtifactPersistenceConfig(
                mode=GraphArtifactRolloutMode.READ_ONLY
            ),
        ),
        graph_result_runtime=HarnessGraphResultRuntime(
            HarnessGraphControlPlaneRuntime(fixture.port)
        ),
        config=GraphArtifactPersistenceConfig(
            mode=GraphArtifactRolloutMode.READ_ONLY
        ),
        tenant_id=TENANT_ID,
        tenant_scope_ref=TENANT_SCOPE_REF,
    )
    before_commits = recovery.activity_result_commits

    with pytest.raises(GraphArtifactResultError) as captured:
        read_only.commit_result(
            activity=recovery.activities[0],
            graph=recovery.graph,
            run_spec_checksum=recovery.run_spec_checksum,
            worker_result=worker_result,
            occurred_at=fixture.envelope.created_at,
        )

    assert (
        captured.value.error_code
        is GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED
    )
    assert empty_attempts.put_count == 0
    assert fixture.port.recover_graph(fixture.run_id).activity_result_commits == (
        before_commits
    )


@pytest.mark.parametrize(
    "field_name",
    ("persistence", "persistence_mode", "retention", "retention_class"),
)
def test_worker_persistence_authority_is_rejected_before_materialization(
    field_name: str,
) -> None:
    fixture = _fixture(node_id="build_reader_payload")

    with pytest.raises(HarnessValidationError) as captured:
        HarnessWorkerResult(
            "succeeded",
            output={
                "reader_payload": {"title": "bounded"},
                field_name: "worker-choice",
            },
        )

    assert captured.value.code == "worker_decision_field_rejected"
    assert fixture.artifact.write_count == 0
    assert fixture.attempts.put_count == 0
    assert fixture.port.recover_graph(fixture.run_id).activity_result_commits == ()


def test_unknown_research_node_fails_closed_before_materialization() -> None:
    fixture = _fixture(node_id="unclassified_research_node")

    with pytest.raises(HarnessValidationError) as captured:
        _execute(fixture, HarnessWorkerResult("succeeded", output={"value": 1}))

    assert captured.value.code == "research_graph_result_policy_missing"
    assert fixture.artifact.write_count == 0
    assert fixture.attempts.put_count == 0
    assert fixture.port.recover_graph(fixture.run_id).activity_result_commits == ()


def test_scope_mismatch_fails_before_materialization() -> None:
    fixture = _fixture(
        node_id="run_research_rag",
        committer_tenant_id="research-scope:sha256:" + "2" * 64,
    )

    with pytest.raises(HarnessValidationError) as captured:
        _execute(fixture, HarnessWorkerResult("succeeded", output={"rag": {}}))

    assert captured.value.code == "graph_result_lineage_scope_mismatch"
    assert fixture.artifact.write_count == 0
    assert fixture.attempts.put_count == 0


def test_restart_reuses_recorded_worker_and_materialized_attempt() -> None:
    port = FailResultProjectionPort()
    fixture = _fixture(node_id="analyze_structure", port=port)
    worker_calls = 0

    def worker(_task: dict) -> HarnessWorkerResult:
        nonlocal worker_calls
        worker_calls += 1
        return HarnessWorkerResult(
            "succeeded",
            output={"structure_candidate": {"summary": "durable"}},
        )

    port.fail_result_projection = True
    with pytest.raises(RuntimeError, match="result projection unavailable"):
        HarnessControlPlane(
            event_port=fixture.port,
            worker_registry={fixture.node_id: worker},
            graph_result_committer=fixture.committer,
        ).run(fixture.run_spec)

    assert worker_calls == 1
    assert fixture.artifact.write_count == 1
    assert fixture.attempts.put_count == 1
    interrupted = fixture.port.recover_graph(fixture.run_id)
    assert len(interrupted.activity_result_commits) == 1
    assert len(interrupted.pending_activity_results) == 1

    port.fail_result_projection = False
    recovered = HarnessControlPlane(
        event_port=fixture.port,
        worker_registry={fixture.node_id: worker},
        graph_result_committer=fixture.committer,
    ).recover_and_run(fixture.run_spec)

    assert recovered.succeeded is True
    assert worker_calls == 1
    assert fixture.artifact.write_count == 1
    assert fixture.attempts.put_count == 1
    completed = fixture.port.recover_graph(fixture.run_id)
    assert len(completed.activity_result_commits) == 1
    assert completed.pending_activity_results == ()


class _Fixture:
    def __init__(
        self,
        *,
        node_id: str,
        run_spec: HarnessRunSpec,
        port,
        committer: ResearchGraphResultCommitter,
        artifact: RecordingArtifactPort,
        attempts: RecordingAttempts,
        catalog: RecordingCatalog,
    ) -> None:
        self.node_id = node_id
        self.run_spec = run_spec
        self.run_id = run_spec.run_id
        self.port = port
        self.committer = committer
        self.artifact = artifact
        self.attempts = attempts
        self.catalog = catalog

    @property
    def envelope(self):
        assert len(self.attempts.envelopes) == 1
        return next(iter(self.attempts.envelopes.values()))

    @property
    def lineage(self):
        commits = self.port.recover_graph(self.run_id).activity_result_commits
        assert len(commits) == 1
        lineage = commits[0].result.result_lineage
        assert lineage is not None
        return lineage


def _run(
    *,
    node_id: str,
    worker_result: HarnessWorkerResult,
) -> _Fixture:
    fixture = _fixture(node_id=node_id)
    _execute(fixture, worker_result)
    return fixture


def _execute(
    fixture: _Fixture,
    worker_result: HarnessWorkerResult,
):
    return HarnessControlPlane(
        event_port=fixture.port,
        worker_registry={fixture.node_id: lambda _task: worker_result},
        graph_result_committer=fixture.committer,
    ).run(fixture.run_spec)


def _fixture(
    *,
    node_id: str,
    port=None,
    committer_tenant_id: str = TENANT_ID,
) -> _Fixture:
    run_id = f"run-research-result-{node_id.replace('_', '-')}"
    event_port = port or InMemoryHarnessEventPort()
    artifact = RecordingArtifactPort()
    attempts = RecordingAttempts()
    catalog = RecordingCatalog()
    config = GraphArtifactPersistenceConfig(
        mode=GraphArtifactRolloutMode.ENFORCE
    )
    materializer = _materializer(
        artifact=artifact,
        attempts=attempts,
        cache=RecordingCache(),
        catalog=catalog,
        quota=RecordingQuota(),
        config=config,
    )
    committer = ResearchGraphResultCommitter(
        materializer=materializer,
        graph_result_runtime=HarnessGraphResultRuntime(
            HarnessGraphControlPlaneRuntime(event_port)
        ),
        config=config,
        tenant_id=committer_tenant_id,
        tenant_scope_ref=checksum_for(committer_tenant_id),
    )
    return _Fixture(
        node_id=node_id,
        run_spec=_run_spec(run_id, node_id),
        port=event_port,
        committer=committer,
        artifact=artifact,
        attempts=attempts,
        catalog=catalog,
    )


def _run_spec(run_id: str, node_id: str) -> HarnessRunSpec:
    step = HarnessStepSpec(
        node_id,
        "script",
        metadata={"step_version": "1", "worker_version": "1"},
    )
    return HarnessRunSpec(
        run_id=run_id,
        workflow=HarnessWorkflowSpec(
            workflow_id="research.paper_analysis",
            workflow_version="1",
            steps=(step,),
            entry_step_id=node_id,
            graph=HarnessGraphSpec(
                graph_id="research.paper_analysis.graph",
                root=StepRef(node_id),
            ),
        ),
        metadata={
            "research_runtime": "single_paper",
            "tenant_scope_ref": TENANT_SCOPE_REF,
            "identity_scope_ref": TENANT_SCOPE_REF,
            "subject_scope_ref": SUBJECT_SCOPE_REF,
        },
        created_at=NOW,
    )
