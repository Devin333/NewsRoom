from __future__ import annotations

import re

from business.research.rag.retrieval.paper_policy import classify_query_intent
from business.research.rag.models import ResearchRetrievalGoal

_SCOPE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class AskPaperUseCase:
    def build_retrieval_goal(self, goal: ResearchRetrievalGoal) -> ResearchRetrievalGoal:
        return goal

    def build_paper_ask_goal(
        self,
        *,
        paper_id: str,
        question: str,
        goal_id: str = "paper-rag-ask",
        memory_namespace: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
    ) -> ResearchRetrievalGoal:
        intent = classify_query_intent(question)
        tenant = _scope_id(tenant_id, "tenant_id")
        user = _scope_id(user_id, "user_id")
        namespace = _memory_namespace(memory_namespace, tenant_id=tenant, user_id=user)
        metadata = {"intent": intent}
        if tenant:
            metadata["tenant_id"] = tenant
        if user:
            metadata["user_id"] = user
        metadata["memory_namespace"] = namespace
        return ResearchRetrievalGoal(
            goal_id=goal_id,
            paper_id=paper_id,
            question=question,
            required_evidence_types=_required_evidence_types(intent),
            allowed_source_refs=[f"arxiv://{paper_id}", paper_id],
            allowed_memory_namespaces=[namespace],
            metadata=metadata,
        )


def _required_evidence_types(intent: str) -> list[str]:
    if intent in {"table_query", "numerical_result"}:
        return ["experiment"]
    if intent == "figure_query":
        return ["experiment"]
    if intent == "formula_query":
        return ["method"]
    if intent in {"citation_query", "contribution", "comparison"}:
        return ["claim_support"]
    return ["method"]


def _memory_namespace(
    namespace: str | None,
    *,
    tenant_id: str,
    user_id: str,
) -> str:
    requested = str(namespace or "").strip()
    if not requested:
        if tenant_id and user_id:
            requested = f"research:tenant:{tenant_id}:user:{user_id}"
        elif tenant_id:
            requested = f"research:tenant:{tenant_id}:public"
        elif user_id:
            requested = f"research:user:{user_id}"
        else:
            requested = "research.public"
    _validate_namespace(requested, tenant_id=tenant_id, user_id=user_id)
    return requested


def _validate_namespace(namespace: str, *, tenant_id: str, user_id: str) -> None:
    if not namespace.strip():
        raise ValueError("memory_namespace is required")
    if tenant_id:
        tenant_prefix = f"research:tenant:{tenant_id}:"
        if not namespace.startswith(tenant_prefix):
            raise ValueError("memory_namespace is outside tenant scope")
        if user_id and namespace != f"{tenant_prefix}user:{user_id}":
            raise ValueError("memory_namespace is outside user scope")
        return
    if user_id and namespace != f"research:user:{user_id}":
        raise ValueError("memory_namespace is outside user scope")


def _scope_id(value: str | None, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not _SCOPE_ID_RE.fullmatch(text):
        raise ValueError(f"{field_name} contains unsupported characters")
    return text


__all__ = ["AskPaperUseCase"]
