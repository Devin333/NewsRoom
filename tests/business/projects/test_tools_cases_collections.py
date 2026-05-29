from __future__ import annotations

from business.projects.dto import CaseSearchQuery, ToolCompareRequest, ToolRecommendRequest, ToolSearchQuery
from business.projects.models import ProjectDataset
from business.projects.service import ProjectDomainService
from tests.business.projects.helpers import project_dataset_payload


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
