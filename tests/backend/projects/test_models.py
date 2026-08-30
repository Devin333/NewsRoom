from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.projects.enums import (
    IntegrationDifficulty,
    LabSessionStatus,
    ProjectType,
    ReuseLevel,
)
from backend.projects.models import (
    CaseComponent,
    DataFlowStep,
    DesignPattern,
    LabGraphEdge,
    LabGraphNode,
    LabGraphState,
    LabQuestion,
    LabSession,
    ModuleCase,
    Project,
    ProjectCapability,
    ProjectDataset,
    ProjectMetricSnapshot,
    ProjectSource,
    ProjectToolProfile,
    WatchSignal,
    WatchlistItem,
    stable_id,
)
from tests.backend.projects.helpers import FIXED_NOW


def test_project_model_normalizes_identity_tags_and_confidence_bounds() -> None:
    project = Project(
        id=" project-langfuse ",
        name=" Langfuse ",
        tags=[" Observability ", "observability", "LLMOps", ""],
        suitable_for=["AI Platform Teams", "ai platform teams"],
        learnable_points=["Tracing", "tracing", "Evaluation"],
        source_confidence=1.25,
    )
    low_confidence_project = Project(id="project-low", name="Low Confidence", source_confidence=-2)

    assert project.id == "project-langfuse"
    assert project.name == "Langfuse"
    assert project.slug == "langfuse"
    assert project.tags == ["Observability", "LLMOps"]
    assert project.suitable_for == ["AI Platform Teams"]
    assert project.learnable_points == ["Tracing", "Evaluation"]
    assert project.source_confidence == 1.0
    assert low_confidence_project.source_confidence == 0.0

    with pytest.raises(ValidationError):
        Project(id=" ", name="Valid Name")
    with pytest.raises(ValidationError):
        Project(id="project-empty-name", name=" ")


def test_metric_snapshot_keeps_absent_public_metrics_unset() -> None:
    snapshot = ProjectMetricSnapshot(
        id="metrics-private-2026-05-29",
        project_id="project-missing-public-metrics",
        snapshot_at=FIXED_NOW,
        internal_views=4,
        internal_saves=1,
        source_mentions=1,
    )

    payload = snapshot.to_dict()

    assert payload["internal_views"] == 4
    assert payload["internal_saves"] == 1
    assert payload["source_mentions"] == 1
    assert "github_stars" not in payload
    assert "product_hunt_votes" not in payload
    assert "hn_points" not in payload
    assert "quality_score" not in payload


def test_project_dataset_preserves_backend_lineage_and_public_sources() -> None:
    project = Project(
        id="project-langfuse",
        name="Langfuse",
        github_url="https://github.com/langfuse/langfuse",
        project_type=ProjectType.TOOL,
    )
    source = ProjectSource(
        id="src-langfuse-github",
        project_id=project.id,
        source_name="GitHub",
        source_type="github",
        source_url="https://github.com/langfuse/langfuse",
        external_id="langfuse/langfuse",
        raw_title="langfuse/langfuse",
        fetched_at=FIXED_NOW,
    )
    dataset = ProjectDataset(
        projects=[project],
        sources=[source],
        source="backend",
        source_run_id="projects-run-2026-05-29",
        generated_at=datetime(2026, 5, 29, 8, 0, tzinfo=UTC),
        notices=["public metadata only"],
    )

    payload = dataset.to_dict()

    assert payload["source"] == "backend"
    assert payload["source_run_id"] == "projects-run-2026-05-29"
    assert payload["projects"][0]["slug"] == "langfuse"
    assert payload["sources"][0]["source_url"] == "https://github.com/langfuse/langfuse"
    assert payload["notices"] == ["public metadata only"]


def test_tool_case_models_capture_bridge_contract() -> None:
    capability = ProjectCapability(
        id="cap-langfuse-tracing",
        project_id="project-langfuse",
        name="LLM Trace Capture",
        capability_type="observability",
        description="Capture prompts, generations, spans, and evaluation metadata.",
        reusable_level=ReuseLevel.HIGH,
        difficulty=IntegrationDifficulty.MEDIUM,
        target_modules=["agent-runtime", "quality-gate"],
    )
    profile = ProjectToolProfile(
        project_id="project-langfuse",
        tool_type="llm-observability",
        input_types=["trace", "prompt"],
        output_types=["dashboard", "metrics"],
        is_open_source=True,
        license="MIT",
        local_deployable=True,
        has_api=True,
        has_python_sdk=True,
        has_docker=True,
        recommended_integration="wrap_as_service",
        target_modules=["agent-runtime", "evaluation"],
        setup_commands=["docker compose up"],
        known_limits=["requires explicit secret configuration"],
        experiment_status="runnable",
    )
    case = ModuleCase(
        id="case-langfuse-tracing",
        project_id="project-langfuse",
        title="Trace-first LLM workflow",
        business_domain="ai-platform",
        module_type="observability",
        problem="Teams need to debug agent runs using public evidence and internal traces.",
        design_summary="Bridge trace collection into evaluation and review workflows.",
        plain_explanation="Capture each model interaction as a trace and attach review signals.",
        design_logic="Trace data becomes evidence for ranking, review, and quality gates.",
        components=[
            CaseComponent(
                id="component-trace-ingestor",
                case_id="case-langfuse-tracing",
                name="Trace Ingestor",
                component_type="adapter",
                responsibility="Convert runtime spans into project evidence.",
                plain_explanation="An adapter receives traces and stores only review-safe fields.",
            )
        ],
        patterns=[
            DesignPattern(
                id="pattern-evidence-bridge",
                case_id="case-langfuse-tracing",
                name="Evidence Bridge",
                pattern_type="integration",
                explanation="Translate tool-specific traces into stable business evidence.",
                when_to_use="Use when public metadata must connect to internal review state.",
                pros=["Keeps UI and service contracts stable"],
                cons=["Needs strict redaction boundaries"],
            )
        ],
        data_flow=[
            DataFlowStep(
                id="flow-trace-to-ranking",
                case_id="case-langfuse-tracing",
                order=1,
                title="Trace to ranking feature",
                description="Trace evidence updates quality and activity ranking features.",
            )
        ],
        source_refs=["src-langfuse-github"],
    )

    assert capability.target_modules == ["agent-runtime", "quality-gate"]
    assert profile.recommended_integration == "wrap_as_service"
    assert profile.experiment_status == "runnable"
    assert case.components[0].plain_explanation.endswith("review-safe fields.")
    assert case.patterns[0].pros == ["Keeps UI and service contracts stable"]
    assert case.data_flow[0].order == 1


def test_watchlist_and_lab_state_models_preserve_user_state() -> None:
    signal = WatchSignal(
        id="signal-langfuse-release",
        project_id="project-langfuse",
        signal_type="release",
        title="Langfuse release",
        summary="A release was detected from a public source.",
        source_url="https://github.com/langfuse/langfuse/releases",
        severity="high",
        occurred_at=FIXED_NOW,
        detected_at=FIXED_NOW,
    )
    watch = WatchlistItem(
        id="watch-user-1-langfuse",
        user_id="user-1",
        project_id="project-langfuse",
        watch_reason="Track observability releases for the agent runtime backlog.",
        watch_topics=["release", "sdk"],
        priority="high",
        next_action="Review release notes",
        signals=[signal],
        created_at=FIXED_NOW,
    )
    graph = LabGraphState(
        session_id="lab-session-1",
        nodes=[
            LabGraphNode(
                id="node-problem",
                node_type="user_problem",
                title="Need trace-backed quality gates",
                payload={"source": "user"},
                weight=1.0,
            ),
            LabGraphNode(
                id="node-case",
                node_type="case",
                title="Trace-first LLM workflow",
                payload={"case_id": "case-langfuse-tracing"},
                weight=0.9,
            ),
        ],
        edges=[
            LabGraphEdge(
                source_id="node-problem",
                target_id="node-case",
                relation_type="matches_case",
                weight=0.86,
                reason="The case maps traces to review evidence.",
            )
        ],
        focused_node_ids=["node-problem", "node-case"],
        hidden_node_ids=[],
    )
    session = LabSession(
        id="lab-session-1",
        user_id="user-1",
        user_problem="Need trace-backed quality gates for agent runs.",
        business_domain="ai-platform",
        module_type="quality-gate",
        target_goal="Draft an integration plan",
        selected_case_ids=["case-langfuse-tracing"],
        graph_state=graph,
        questions=[
            LabQuestion(
                id="question-1",
                session_id="lab-session-1",
                question="Which integration depth is acceptable?",
                question_type="single_choice",
                options=[{"label": "Wrap as service", "value": "wrap_as_service"}],
                purpose="Choose implementation depth.",
                answered_value="wrap_as_service",
            )
        ],
        status=LabSessionStatus.ACTIVE,
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
    )

    assert watch.notify_on == ["release", "docs_change", "hot_score"]
    assert watch.signals[0].severity == "high"
    assert session.graph_state.focused_node_ids == ["node-problem", "node-case"]
    assert session.graph_state.edges[0].relation_type == "matches_case"
    assert session.questions[0].answered_value == "wrap_as_service"
    assert session.status == LabSessionStatus.ACTIVE


def test_stable_id_is_deterministic_for_project_bridge_records() -> None:
    first = stable_id("project", "Langfuse", "https://github.com/langfuse/langfuse")
    second = stable_id("project", "langfuse", "https://github.com/langfuse/langfuse")

    assert first == second
    assert first.startswith("project_")
