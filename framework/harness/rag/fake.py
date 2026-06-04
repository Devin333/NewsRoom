from __future__ import annotations

from framework.harness.rag.models import RAGContextPack, RAGSessionRequest
from framework.harness.retrieval.fake import FakeRetrievalPort
from framework.harness.retrieval.request import RetrievalRequest


class FakeRAGPlanner:
    def plan(self, request: RAGSessionRequest) -> tuple[RetrievalRequest, ...]:
        return (RetrievalRequest(query=request.query, limit=5, context_refs=request.context_refs),)


class FakeRAGSessionController:
    def __init__(self, retrieval: FakeRetrievalPort | None = None, planner: FakeRAGPlanner | None = None) -> None:
        self.retrieval = retrieval or FakeRetrievalPort()
        self.planner = planner or FakeRAGPlanner()
        self.requests: list[RAGSessionRequest] = []

    def build_context_pack(self, request: RAGSessionRequest) -> RAGContextPack:
        self.requests.append(request)
        retrieval_requests = self.planner.plan(request)
        evidence = []
        for retrieval_request in retrieval_requests[: request.max_rounds]:
            evidence.extend(self.retrieval.retrieve(retrieval_request).packs)
        return RAGContextPack(
            pack_id=f"rag://fake/{len(self.requests)}",
            query=request.query,
            evidence=tuple(evidence),
            context_refs=request.context_refs,
            metadata={"rounds": min(len(retrieval_requests), request.max_rounds)},
        )


__all__ = ["FakeRAGPlanner", "FakeRAGSessionController"]
