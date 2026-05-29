from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from business.projects.dto import (
    LabAnswerRequest,
    LabNodeExplainRequest,
    LabNodeExplainResult,
    LabSaveRequest,
    LabSessionRequest,
    LabSolutionResult,
)
from business.projects.enums import LabSessionStatus
from business.projects.models import (
    LabGraphEdge,
    LabGraphNode,
    LabGraphState,
    LabQuestion,
    LabSession,
    LabSolution,
    ModuleCase,
    ProjectDataset,
    stable_id,
)
from business.projects.repository import ProjectStateRepository


class ProjectLabService:
    def __init__(self, state_repository: ProjectStateRepository) -> None:
        self.state_repository = state_repository

    def start_session(self, dataset: ProjectDataset, request: LabSessionRequest) -> LabSession:
        if not request.user_problem.strip():
            raise ValueError("user_problem is required")
        selected_cases = _select_cases(dataset, request)
        session_id = stable_id("lab_session", request.user_id or "anonymous", request.user_problem, _now().isoformat())
        profile = _requirement_profile(request, selected_cases)
        graph = _build_graph(session_id, request, selected_cases)
        questions = _questions(session_id, request, dataset, selected_cases)
        session = LabSession(
            id=session_id,
            user_id=request.user_id,
            user_problem=request.user_problem.strip(),
            business_domain=request.business_domain,
            module_type=request.module_type,
            target_goal=request.target_goal,
            current_project_context=request.current_project_context,
            requirement_profile=profile,
            selected_case_ids=[case.id for case in selected_cases],
            graph_state=graph,
            questions=questions,
            current_stage="clarifying_requirements",
            status=LabSessionStatus.ACTIVE,
        )
        self.state_repository.update(
            lambda state: state.model_copy(update={"lab_sessions": [*state.lab_sessions, session]})
        )
        return session

    def get_session(self, session_id: str) -> LabSession | None:
        for session in self.state_repository.load().lab_sessions:
            if session.id == session_id:
                return session
        return None

    def answer(self, session_id: str, request: LabAnswerRequest) -> LabSession | None:
        updated: LabSession | None = None

        def update(state):
            nonlocal updated
            sessions: list[LabSession] = []
            for session in state.lab_sessions:
                if session.id != session_id:
                    sessions.append(session)
                    continue
                questions = [
                    question.model_copy(update={"answered_value": request.answer})
                    if question.id == request.question_id
                    else question
                    for question in session.questions
                ]
                answered = any(question.id == request.question_id for question in session.questions)
                if not answered:
                    sessions.append(session)
                    continue
                node = LabGraphNode(
                    id=stable_id("lab_node", session_id, request.question_id, "answer"),
                    node_type="feedback",
                    title="User clarification",
                    payload={"question_id": request.question_id, "answer": request.answer},
                )
                graph = session.graph_state.model_copy(
                    update={
                        "nodes": [*session.graph_state.nodes, node],
                        "edges": [
                            *session.graph_state.edges,
                            LabGraphEdge(
                                source_id=request.question_id,
                                target_id=node.id,
                                relation_type="answered_by",
                                reason="User answered a Lab clarification question.",
                            ),
                        ],
                        "focused_node_ids": [node.id],
                    }
                )
                updated = session.model_copy(
                    update={
                        "questions": questions,
                        "graph_state": graph,
                        "current_stage": "solution_ready",
                        "updated_at": _now(),
                    }
                )
                sessions.append(updated)
            return state.model_copy(update={"lab_sessions": sessions})

        self.state_repository.update(update)
        return updated

    def explain_node(self, session_id: str, request: LabNodeExplainRequest) -> LabNodeExplainResult | None:
        session = self.get_session(session_id)
        if session is None:
            return None
        node = next((item for item in session.graph_state.nodes if item.id == request.node_id), None)
        if node is None:
            return None
        related_nodes = [
            {
                "id": related.id,
                "title": related.title,
                "node_type": related.node_type,
                "relation": edge.relation_type,
                "reason": edge.reason,
            }
            for edge in session.graph_state.edges
            for related in session.graph_state.nodes
            if (
                edge.source_id == node.id
                and related.id == edge.target_id
            )
            or (
                edge.target_id == node.id
                and related.id == edge.source_id
            )
        ]
        return LabNodeExplainResult(
            session_id=session.id,
            node_id=node.id,
            title=node.title,
            explanation=_node_explanation(node, request.style),
            related_nodes=related_nodes,
        )

    def generate_solution(self, dataset: ProjectDataset, session_id: str) -> LabSolutionResult | None:
        result: LabSolutionResult | None = None

        def update(state):
            nonlocal result
            sessions: list[LabSession] = []
            for session in state.lab_sessions:
                if session.id != session_id:
                    sessions.append(session)
                    continue
                cases = [case for case in dataset.cases if case.id in session.selected_case_ids]
                solution = _solution(session, cases, dataset)
                solution_node = LabGraphNode(
                    id=stable_id("lab_node", session.id, "solution"),
                    node_type="solution",
                    title=solution.title,
                    payload=solution.solution_json,
                )
                graph = session.graph_state.model_copy(
                    update={
                        "nodes": [*session.graph_state.nodes, solution_node],
                        "focused_node_ids": [solution_node.id],
                    }
                )
                updated = session.model_copy(
                    update={
                        "generated_solution": solution.markdown,
                        "solution_json": solution.solution_json,
                        "graph_state": graph,
                        "current_stage": "solution_generated",
                        "status": LabSessionStatus.ACTIVE,
                        "updated_at": _now(),
                    }
                )
                sessions.append(updated)
                result = LabSolutionResult(session=updated, solution=solution.to_dict())
            return state.model_copy(update={"lab_sessions": sessions})

        self.state_repository.update(update)
        return result

    def save_session(self, session_id: str, request: LabSaveRequest) -> LabSession | None:
        updated: LabSession | None = None

        def update(state):
            nonlocal updated
            sessions: list[LabSession] = []
            for session in state.lab_sessions:
                if session.id != session_id:
                    sessions.append(session)
                    continue
                metadata = dict(session.graph_state.metadata)
                if request.note:
                    metadata["save_note"] = request.note
                graph = session.graph_state.model_copy(update={"metadata": metadata})
                updated = session.model_copy(
                    update={
                        "status": LabSessionStatus(request.status),
                        "graph_state": graph,
                        "current_stage": f"solution_{request.status}",
                        "updated_at": _now(),
                    }
                )
                sessions.append(updated)
            return state.model_copy(update={"lab_sessions": sessions})

        self.state_repository.update(update)
        return updated


def _select_cases(dataset: ProjectDataset, request: LabSessionRequest) -> list[ModuleCase]:
    explicit = {case_id for case_id in request.selected_case_ids if case_id}
    if explicit:
        return [case for case in dataset.cases if case.id in explicit]
    request_text = " ".join(
        item
        for item in [request.user_problem, request.business_domain, request.module_type, request.target_goal]
        if item
    ).casefold()
    cases = sorted(
        dataset.cases,
        key=lambda case: _case_similarity(case, request_text),
        reverse=True,
    )
    return [case for case in cases if _case_similarity(case, request_text) > 0][:4]


def _case_similarity(case: ModuleCase, request_text: str) -> float:
    haystack = " ".join(
        [
            case.title,
            case.business_domain,
            case.module_type,
            case.problem,
            case.design_summary,
            " ".join(case.suitable_for),
        ]
    ).casefold()
    tokens = {token for token in request_text.split() if len(token) > 2}
    if not tokens:
        return 0.0
    return sum(1 for token in tokens if token in haystack) / len(tokens)


def _requirement_profile(request: LabSessionRequest, selected_cases: list[ModuleCase]) -> dict[str, Any]:
    return {
        "problem": request.user_problem.strip(),
        "business_domain": request.business_domain,
        "module_type": request.module_type,
        "target_goal": request.target_goal,
        "current_project_context": request.current_project_context,
        "matched_case_count": len(selected_cases),
        "matched_domains": sorted({case.business_domain for case in selected_cases}),
        "matched_module_types": sorted({case.module_type for case in selected_cases}),
        "data_policy": "Cases and project references are derived from real Project Radar artifacts only.",
    }


def _build_graph(session_id: str, request: LabSessionRequest, selected_cases: list[ModuleCase]) -> LabGraphState:
    problem_node = LabGraphNode(
        id=stable_id("lab_node", session_id, "problem"),
        node_type="user_problem",
        title="User problem",
        payload={"text": request.user_problem},
    )
    nodes = [problem_node]
    edges: list[LabGraphEdge] = []
    for case in selected_cases:
        case_node = LabGraphNode(
            id=stable_id("lab_node", session_id, case.id),
            node_type="case",
            title=case.title,
            payload={"case_id": case.id, "project_id": case.project_id, "module_type": case.module_type},
            weight=1.2,
        )
        nodes.append(case_node)
        edges.append(
            LabGraphEdge(
                source_id=problem_node.id,
                target_id=case_node.id,
                relation_type="similar_to",
                weight=0.8,
                reason="Case selected by deterministic requirement similarity.",
            )
        )
    return LabGraphState(
        session_id=session_id,
        nodes=nodes,
        edges=edges,
        focused_node_ids=[problem_node.id],
        metadata={"case_count": len(selected_cases)},
    )


def _questions(
    session_id: str,
    request: LabSessionRequest,
    dataset: ProjectDataset,
    selected_cases: list[ModuleCase],
) -> list[LabQuestion]:
    questions = [
        LabQuestion(
            id=stable_id("lab_question", session_id, "success_metric"),
            session_id=session_id,
            question="What is the primary success metric for this module?",
            question_type="free_text",
            purpose="Clarify acceptance criteria before generating a solution.",
        )
    ]
    if request.module_type is None:
        questions.append(
            LabQuestion(
                id=stable_id("lab_question", session_id, "module_type"),
                session_id=session_id,
                question="Which module type is closest to your target?",
                question_type="single_choice",
                options=[
                    {"label": value, "value": value}
                    for value in sorted({case.module_type for case in dataset.cases} or {"workflow", "retrieval", "evaluation"})
                ],
                purpose="Align the Lab plan with reusable module patterns.",
            )
        )
    if not selected_cases:
        questions.append(
            LabQuestion(
                id=stable_id("lab_question", session_id, "no_case_constraint"),
                session_id=session_id,
                question="No real-derived similar case is available yet. Should the solution be conservative and source-first?",
                question_type="confirm",
                options=[{"label": "Yes", "value": "yes"}, {"label": "No", "value": "no"}],
                purpose="Avoid inventing case references when Project Radar has no match.",
            )
        )
    return questions


def _solution(session: LabSession, cases: list[ModuleCase], dataset: ProjectDataset) -> LabSolution:
    case_lines = [
        f"- {case.title}: {case.design_summary or case.plain_explanation}"
        for case in cases
    ]
    if not case_lines:
        case_lines = ["- No similar case is available from real Project Radar artifacts; validate sources before adoption."]
    project_refs = [
        project
        for project in dataset.projects
        if any(case.project_id == project.id for case in cases)
    ]
    components = sorted({component.name for case in cases for component in case.components}) or ["Requirement intake", "Evidence review", "Implementation plan"]
    markdown = "\n".join(
        [
            f"# {session.user_problem[:80]}",
            "",
            "## Requirement Profile",
            f"- Domain: {session.business_domain or 'unspecified'}",
            f"- Module type: {session.module_type or 'unspecified'}",
            f"- Goal: {session.target_goal or 'unspecified'}",
            "",
            "## Real-Derived References",
            *case_lines,
            "",
            "## Proposed Shape",
            *[f"- {component}" for component in components],
            "",
            "## Minimum Viable Version",
            "- Start with one end-to-end path that captures the request, attaches source evidence, and produces an auditable result.",
            "- Reuse only the components that match the selected case inputs and outputs.",
            "- Add regression checks before expanding the workflow surface.",
            "",
            "## Non-Goals",
            "- Do not add synthetic project, case, or metric records to make the solution look complete.",
            "- Do not automate code changes or prompt rollout from this Lab proposal.",
            "- Do not ingest paid or inaccessible source content.",
            "",
            "## Guardrails",
            "- Do not rely on unverified or synthetic project data.",
            "- Re-check Project Radar source references before implementation.",
        ]
    )
    return LabSolution(
        id=stable_id("lab_solution", session.id),
        session_id=session.id,
        title="Projects Lab solution",
        markdown=markdown,
        solution_json={
            "problem": session.user_problem,
            "components": components,
            "case_ids": [case.id for case in cases],
            "project_ids": [project.id for project in project_refs],
            "minimum_viable_version": [
                "One auditable path from user request to evidence-backed output.",
                "Only case-matched components are reused in the first pass.",
                "Regression checks guard expansion.",
            ],
            "non_goals": [
                "Synthetic project or case records.",
                "Automatic code changes or prompt rollout.",
                "Paid or inaccessible source ingestion.",
            ],
            "data_policy": "real_project_radar_only",
        },
        review_notes=[
            "Solution uses deterministic requirement matching.",
            "No synthetic cases are added when Project Radar has no matching case.",
        ],
    )


def _now() -> datetime:
    return datetime.now(UTC)


def _node_explanation(node: LabGraphNode, style: str) -> str:
    payload = node.payload
    if node.node_type == "user_problem":
        return f"This node captures the original user problem: {payload.get('text', node.title)}"
    if node.node_type == "case":
        return (
            f"This case node links the Lab problem to real-derived case {payload.get('case_id')} "
            f"from project {payload.get('project_id')}."
        )
    if node.node_type == "solution":
        if style == "technical":
            return f"This solution node contains generated JSON keys: {', '.join(sorted(payload.keys()))}."
        return "This node contains the generated Lab proposal, including MVP scope, non-goals, and source policy."
    if node.node_type == "feedback":
        return f"This node records a user clarification for question {payload.get('question_id')}."
    return f"This {node.node_type} node supports the Lab reasoning graph for {node.title}."
