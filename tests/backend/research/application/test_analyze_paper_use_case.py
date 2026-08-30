from __future__ import annotations

from collections.abc import Callable

import pytest

import backend.research.application.single_paper_runtime as single_paper_runtime
from framework.agent.artifacts.paths import ArtifactPathError
from framework.harness import (
    FakeArtifactPort,
    HarnessEvent,
    HarnessTransitionPort,
    InMemoryHarnessEventPort,
)

from backend.research.application import AnalyzePaperRequest, AnalyzePaperUseCase
from backend.research.application.single_paper_runtime import ResearchSinglePaperRuntime
from tests.backend.research.fakes import (
    FakeGithubRepositoryPort,
    FakeResearchDocumentCompiler,
    FakeResearchLLMWorker,
    FakeResearchRAGRuntime,
    FakeResearchSourceProvider,
    in_memory_node_output_resource_factory,
)


class _WriteOnlyHarnessTransitionPort:
    """Transition-capable test adapter without a public event buffer."""

    def __init__(self) -> None:
        self._delegate = InMemoryHarnessEventPort()
        self.record_count = 0

    def record(self, event: HarnessEvent) -> HarnessEvent:
        self.record_count += 1
        return self._delegate.record(event)

    def read_history(self, *args, **kwargs):
        return self._delegate.read_history(*args, **kwargs)

    def require_activity_storage(self) -> None:
        self._delegate.require_activity_storage()

    def accept_graph_activity(self, *args, **kwargs):
        return self._delegate.accept_graph_activity(*args, **kwargs)

    def resolve_graph_replay_activity(self, *args, **kwargs):
        return self._delegate.resolve_graph_replay_activity(*args, **kwargs)

    def record_graph_activity_result(self, *args, **kwargs):
        return self._delegate.record_graph_activity_result(*args, **kwargs)

    def record_graph_phase_transition(self, *args, **kwargs):
        return self._delegate.record_graph_phase_transition(*args, **kwargs)

    def initialize_graph(self, *args, **kwargs):
        return self._delegate.initialize_graph(*args, **kwargs)

    def commit_graph_decision(self, *args, **kwargs):
        return self._delegate.commit_graph_decision(*args, **kwargs)

    def commit_graph_projection(self, *args, **kwargs):
        return self._delegate.commit_graph_projection(*args, **kwargs)

    def commit_graph_activity_result(self, *args, **kwargs):
        return self._delegate.commit_graph_activity_result(*args, **kwargs)

    def commit_graph_observation(self, *args, **kwargs):
        return self._delegate.commit_graph_observation(*args, **kwargs)

    def recover_graph(self, *args, **kwargs):
        return self._delegate.recover_graph(*args, **kwargs)

    def activity_for(self, *args, **kwargs):
        return self._delegate.activity_for(*args, **kwargs)

    def mark_activity_dispatched(self, *args, **kwargs):
        return self._delegate.mark_activity_dispatched(*args, **kwargs)


def _use_case(
    *,
    llm: FakeResearchLLMWorker | None = None,
    compiler: FakeResearchDocumentCompiler | None = None,
    rag: FakeResearchRAGRuntime | None = None,
    artifact_port: FakeArtifactPort | None = None,
    event_port_factory: Callable[[str], HarnessTransitionPort] | None = None,
) -> AnalyzePaperUseCase:
    runtime = ResearchSinglePaperRuntime(
        source_provider=FakeResearchSourceProvider(),
        document_compiler=compiler or FakeResearchDocumentCompiler(),
        llm_worker=llm or FakeResearchLLMWorker(),
        github_repository=FakeGithubRepositoryPort(),
        rag_runtime=rag or FakeResearchRAGRuntime(),
        artifact_port=artifact_port or FakeArtifactPort(),
        event_port_factory=event_port_factory
        or (lambda run_id: InMemoryHarnessEventPort()),
        node_output_resource_factory=in_memory_node_output_resource_factory,
    )
    return AnalyzePaperUseCase(runtime)


def test_analyze_paper_use_case_runs_single_paper_loop_successfully() -> None:
    result = _use_case().analyze(
        AnalyzePaperRequest(
            run_id="research-run-success",
            paper_id="paper-harness-001",
            source_ref="https://arxiv.org/abs/2606.00123",
            user_id="user-1",
        )
    )

    assert result.succeeded is True
    assert result.analysis is not None
    assert result.reader_payload is not None
    assert result.paper_card is not None
    assert result.paper_card.github_stars == 124
    assert result.paper_card.github_star_growth_daily == 12.0
    assert result.paper_card.reader_payload_status == "ready"
    assert result.quality.passed is True
    assert result.trace_ref == "harness-trace://research-run-success"
    assert "research-analysis" in result.artifact_refs
    assert "research-reader-payload" in result.artifact_refs
    assert "research-paper-card" in result.artifact_refs
    assert result.skill_experience_refs


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ({}, 3),
        ({"rag_max_replans": 0}, 0),
        ({"rag_max_replans": 4}, 4),
        ({"rag_max_replans": " 2 "}, 2),
    ],
)
def test_research_rag_replan_budget_defaults_and_explicit_bounds(
    options: dict[str, object],
    expected: int,
) -> None:
    budget = single_paper_runtime._rag_budget_from_options(options)

    assert budget.max_replans == expected


@pytest.mark.parametrize(
    "value",
    [-1, 5, True, 1.5, "2.0", "invalid", None],
)
def test_research_rag_replan_budget_rejects_invalid_values(value: object) -> None:
    with pytest.raises(
        ValueError,
        match="rag_max_replans must be an integer between 0 and 4",
    ):
        single_paper_runtime._rag_budget_from_options(
            {"rag_max_replans": value}
        )


def test_analyze_uses_committed_events_without_reading_port_storage() -> None:
    event_port = _WriteOnlyHarnessTransitionPort()

    result = _use_case(event_port_factory=lambda run_id: event_port).analyze(
        AnalyzePaperRequest(
            run_id="research-run-write-only-event-port",
            paper_id="paper-harness-001",
            source_ref="https://arxiv.org/abs/2606.00123",
            user_id="user-1",
        )
    )

    assert result.succeeded is True
    assert event_port.record_count > 0
    assert result.trace.events


def test_analyze_rejects_unsafe_run_id_before_event_port_factory() -> None:
    factory_calls: list[str] = []

    def event_port_factory(run_id: str) -> HarnessTransitionPort:
        factory_calls.append(run_id)
        return _WriteOnlyHarnessTransitionPort()

    with pytest.raises(ArtifactPathError, match="single path segment"):
        _use_case(event_port_factory=event_port_factory).analyze(
            AnalyzePaperRequest(
                run_id="../escape",
                paper_id="paper-harness-001",
                source_ref="https://arxiv.org/abs/2606.00123",
                user_id="user-1",
            )
        )

    assert factory_calls == []


def test_llm_flow_control_candidate_does_not_route_workflow() -> None:
    result = _use_case(llm=FakeResearchLLMWorker(include_flow_control_field=True)).analyze(
        AnalyzePaperRequest(
            run_id="research-run-flow-field",
            paper_id="paper-harness-001",
            source_ref="https://arxiv.org/abs/2606.00123",
        )
    )

    assert result.succeeded is True
    analyze_structure_result = next(
        item
        for item in result.diagnostics["worker_results"].values()
        if item["node_id"] == "analyze_structure"
    )
    assert analyze_structure_result["output"]["warnings"] == ["next_step"]
    assert "publish_artifacts" in [entry.node_id for entry in result.transcript.entries()]


def test_missing_evidence_halts_after_replan_budget_is_exhausted() -> None:
    result = _use_case(llm=FakeResearchLLMWorker(missing_evidence=True)).analyze(
        AnalyzePaperRequest(
            run_id="research-run-missing-evidence",
            paper_id="paper-harness-001",
            source_ref="https://arxiv.org/abs/2606.00123",
            options={"max_replans": 0},
        )
    )

    assert result.status == "halted"
    assert result.quality.passed is False
    assert result.diagnostics["terminal_reason"] == "verification_failed_replans_exhausted"
    failure = next(
        failure
        for failure in result.diagnostics["gate_failures"]
        if failure["gate"] == "ClaimEvidenceGate"
    )
    assert failure["details"]["harness_gate"]["reference"] == "ClaimEvidenceGate@1"
