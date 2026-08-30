from __future__ import annotations

from backend.projects.dto import (
    CaseExplainRequest,
    CaseMapRequest,
    CaseSearchQuery,
    CollectionCreateRequest,
    CollectionGenerateRequest,
    CollectionItemCreateRequest,
    ToolCompareRequest,
    ToolRecommendRequest,
    ToolSearchQuery,
)
from backend.projects.models import ProjectDataset
from backend.projects.repository import ProjectStateRepository
from backend.projects.service import ProjectDomainService
from tests.backend.projects.helpers import project_dataset_payload


class _StaticArtifactRepository:
    def load_dataset(self):
        return ProjectDataset.model_validate(project_dataset_payload())


def test_tools_search_compare_and_recommend_use_real_derived_profiles(tmp_path) -> None:
    service = ProjectDomainService(artifact_repository=_StaticArtifactRepository())

    search = service.search_tools(ToolSearchQuery(q="observability", limit=5))
    compare = service.compare_tools(ToolCompareRequest(project_ids=["project-langfuse"]))
    recommend = service.recommend_tools(ToolRecommendRequest(problem="Need trace evals", target_module="evaluation"))

    assert search.tools[0].project.id == "project-langfuse"
    assert compare.matrix[0]["project_id"] == "project-langfuse"
    assert recommend.tools[0].project.id == "project-langfuse"
    assert recommend.reasoning


def test_cases_and_collections_are_searchable_from_dataset() -> None:
    service = ProjectDomainService(artifact_repository=_StaticArtifactRepository())

    cases = service.search_cases(CaseSearchQuery(q="trace", limit=5))
    collections = service.list_collections()
    collection = service.get_collection("llm-observability-stack")

    assert cases.cases[0].id == "case-langfuse-tracing"
    assert collections.collections[0].slug == "llm-observability-stack"
    assert collection is not None
    assert collection.item_count == 1


def test_case_explain_and_context_mapping_are_derived_from_real_case() -> None:
    service = ProjectDomainService(artifact_repository=_StaticArtifactRepository())

    explanation = service.explain_case(
        "case-langfuse-tracing",
        CaseExplainRequest(style="migration", user_context="Need trace-backed evaluation gates."),
    )
    mapping = service.map_case_to_context(
        "case-langfuse-tracing",
        CaseMapRequest(user_context="Need trace-backed evaluation gates.", target_module="evaluation"),
    )

    assert explanation is not None
    assert explanation.case_id == "case-langfuse-tracing"
    assert explanation.source_refs == ["src-langfuse-github", "src-langfuse-docs"]
    assert explanation.component_explanations[0]["name"] == "Trace Ingestor"
    assert mapping is not None
    assert mapping.fit_score > 0
    assert mapping.reusable_components[0]["id"] == "component-trace-ingestor"


def test_collection_create_add_item_and_generate_persist_to_state(tmp_path) -> None:
    state = ProjectStateRepository(tmp_path / "state.json")
    service = ProjectDomainService(
        artifact_repository=_StaticArtifactRepository(),
        state_repository=state,
    )

    created = service.create_collection(
        CollectionCreateRequest(
            title="Agent Evaluation Picks",
            description="Projects and cases for evaluation workflows.",
            tags=["evaluation"],
        )
    )
    updated = service.add_collection_item(
        created.collection.id,
        CollectionItemCreateRequest(
            item_type="project",
            item_id="project-langfuse",
            title="Langfuse",
            reason="Trace and evaluation evidence are relevant.",
        ),
    )
    generated = service.generate_collection(CollectionGenerateRequest(topic="observability"))

    saved_collections = state.load().user_collections
    assert created.collection.slug == "agent-evaluation-picks"
    assert updated is not None
    assert updated.collection.item_count == 1
    assert generated.collection.item_count >= 1
    assert {collection.id for collection in saved_collections} >= {created.collection.id, generated.collection.id}
