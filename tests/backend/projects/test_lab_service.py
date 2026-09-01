from __future__ import annotations

import pytest

from backend.projects.lab import (
    LabAnswerValidationError,
    LabQuestionNotFoundError,
    LabSessionNotReadyError,
    LabSolutionMissingError,
)
from backend.projects.dto import LabAnswerRequest, LabNodeExplainRequest, LabSaveRequest, LabSessionRequest
from backend.projects.models import ProjectDataset
from backend.projects.repository import ProjectStateRepository
from backend.projects.service import ProjectDomainService
from tests.backend.projects.helpers import project_dataset_payload


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
    fetched = service.get_lab_session(session.id)
    explained = service.explain_lab_node(
        session.id,
        LabNodeExplainRequest(node_id=session.graph_state.nodes[0].id),
    )
    solution = service.generate_lab_solution(session.id)
    saved = service.save_lab_session(session.id, LabSaveRequest(status="saved", note="Ready for backlog review."))

    assert session.requirement_profile["matched_case_count"] == 1
    assert session.current_stage == "clarifying_requirements"
    assert session.next_action == "answer_question"
    assert session.can_generate_solution is False
    assert session.unanswered_question_ids == [question.id for question in session.questions]
    assert session.graph_state.nodes
    assert session.questions
    assert fetched is not None
    assert fetched.id == session.id
    assert explained is not None
    assert "original user problem" in explained.explanation
    assert answered is not None
    assert answered.questions[0].answered_value == "Release quality score"
    assert solution is not None
    assert solution.solution["solution_json"]["data_policy"] == "real_project_radar_only"
    assert solution.solution["solution_json"]["minimum_viable_version"]
    assert solution.solution["solution_json"]["non_goals"]
    assert saved is not None
    assert saved.status.value == "saved"
    assert saved.current_stage == "solution_saved"
    assert saved.next_action == "none"


def test_lab_workflow_requires_all_questions_and_preserves_unrelated_answers(tmp_path) -> None:
    service = ProjectDomainService(
        artifact_repository=_StaticArtifactRepository(),
        state_repository=ProjectStateRepository(tmp_path / "state.json"),
    )

    session = service.start_lab_session(LabSessionRequest(user_problem="Need a workflow module."))
    assert len(session.questions) >= 2

    first = service.answer_lab_question(
        session.id,
        LabAnswerRequest(question_id=session.questions[0].id, answer="  throughput  "),
    )
    assert first is not None
    assert first.questions[0].answered_value == "throughput"
    assert first.current_stage == "clarifying_requirements"
    assert first.next_action == "answer_question"
    assert first.can_generate_solution is False
    assert first.unanswered_question_ids == [question.id for question in first.questions[1:]]

    with pytest.raises(LabSessionNotReadyError) as exc_info:
        service.generate_lab_solution(session.id)
    assert exc_info.value.unanswered_question_ids == first.unanswered_question_ids
    persisted = service.get_lab_session(session.id)
    assert persisted is not None
    assert persisted.generated_solution is None
    assert persisted.questions[0].answered_value == "throughput"

    completed = service.answer_lab_question(
        session.id,
        LabAnswerRequest(question_id=session.questions[1].id, answer="  local deployment  "),
    )
    assert completed is not None
    assert completed.current_stage == "ready_to_generate"
    assert completed.next_action == "generate_solution"
    assert completed.can_generate_solution is True
    assert completed.unanswered_question_ids == []
    assert completed.questions[0].answered_value == "throughput"
    assert completed.questions[1].answered_value == "local deployment"


def test_lab_answer_validation_unknown_question_and_idempotent_reanswer(tmp_path) -> None:
    service = ProjectDomainService(
        artifact_repository=_StaticArtifactRepository(),
        state_repository=ProjectStateRepository(tmp_path / "state.json"),
    )
    session = service.start_lab_session(
        LabSessionRequest(user_problem="Need an observability module.", module_type="observability")
    )

    with pytest.raises(LabAnswerValidationError):
        service.answer_lab_question(session.id, LabAnswerRequest(question_id=session.questions[0].id, answer="   "))
    unchanged = service.get_lab_session(session.id)
    assert unchanged is not None
    assert unchanged.questions[0].answered_value is None

    with pytest.raises(LabQuestionNotFoundError):
        service.answer_lab_question(session.id, LabAnswerRequest(question_id="missing-question", answer="value"))
    unchanged_again = service.get_lab_session(session.id)
    assert unchanged_again is not None
    assert unchanged_again.graph_state.nodes == unchanged.graph_state.nodes

    answered = service.answer_lab_question(
        session.id,
        LabAnswerRequest(question_id=session.questions[0].id, answer="metric"),
    )
    assert answered is not None
    node_count = len(answered.graph_state.nodes)
    repeated = service.answer_lab_question(
        session.id,
        LabAnswerRequest(question_id=session.questions[0].id, answer="  metric  "),
    )
    assert repeated is not None
    assert repeated.questions[0].answered_value == "metric"
    assert len(repeated.graph_state.nodes) == node_count


def test_lab_save_requires_generated_solution_and_preserves_explicit_statuses(tmp_path) -> None:
    service = ProjectDomainService(
        artifact_repository=_StaticArtifactRepository(),
        state_repository=ProjectStateRepository(tmp_path / "state.json"),
    )
    session = service.start_lab_session(
        LabSessionRequest(user_problem="Need a workflow module.", module_type="observability")
    )

    with pytest.raises(LabSolutionMissingError):
        service.save_lab_session(session.id, LabSaveRequest(status="saved"))
    assert service.get_lab_session(session.id).status.value == "active"

    service.answer_lab_question(
        session.id,
        LabAnswerRequest(question_id=session.questions[0].id, answer="metric"),
    )
    service.generate_lab_solution(session.id)
    adopted = service.save_lab_session(session.id, LabSaveRequest(status="adopted", note="  use in sprint  "))
    assert adopted is not None
    assert adopted.status.value == "adopted"
    assert adopted.current_stage == "solution_adopted"
    assert adopted.next_action == "none"
    assert adopted.graph_state.metadata["save_note"] == "use in sprint"

    archived = service.save_lab_session(session.id, LabSaveRequest(status="archived"))
    assert archived is not None
    assert archived.status.value == "archived"
    assert archived.current_stage == "solution_archived"
    assert archived.next_action == "none"


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
