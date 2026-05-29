from __future__ import annotations

from business.projects.dto import LabAnswerRequest, LabSessionRequest
from business.projects.models import ProjectDataset
from business.projects.repository import ProjectStateRepository
from business.projects.service import ProjectDomainService
from tests.business.projects.helpers import project_dataset_payload


class _StaticArtifactRepository:
    def load_dataset(self):
        return ProjectDataset.model_validate(project_dataset_payload())


def test_lab_session_generates_profile_graph_question_and_solution(tmp_path) -> None:
    service = ProjectDomainService(
        artifact_repository=_StaticArtifactRepository(),
        state_repository=ProjectStateRepository(tmp_path / "state.json"),
    )

    session = service.start_lab_session(
        LabSessionRequest(
            user_problem="Need trace-backed quality gates for agent runs.",
            business_domain="ai-platform",
            module_type="observability",
        )
    )
    answered = service.answer_lab_question(
        session.id,
        LabAnswerRequest(question_id=session.questions[0].id, answer="Release quality score"),
    )
    solution = service.generate_lab_solution(session.id)

    assert session.requirement_profile["matched_case_count"] == 1
    assert session.graph_state.nodes
    assert session.questions
    assert answered is not None
    assert answered.questions[0].answered_value == "Release quality score"
    assert solution is not None
    assert solution.solution["solution_json"]["data_policy"] == "real_project_radar_only"


def test_lab_session_without_cases_does_not_invent_case_references(tmp_path) -> None:
    payload = project_dataset_payload()
    payload["cases"] = []
    service = ProjectDomainService(
        artifact_repository=_StaticArtifactRepositoryNoCases(payload),
        state_repository=ProjectStateRepository(tmp_path / "state.json"),
    )

    session = service.start_lab_session(LabSessionRequest(user_problem="Need a new module."))

    assert session.selected_case_ids == []
    assert session.requirement_profile["matched_case_count"] == 0
    assert any("No real-derived similar case" in question.question for question in session.questions)


class _StaticArtifactRepositoryNoCases:
    def __init__(self, payload):
        self.payload = payload

    def load_dataset(self):
        return ProjectDataset.model_validate(self.payload)
