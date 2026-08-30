from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.memory.feedback_memory import FeedbackMemory, FeedbackMemoryService
from backend.memory.intelligence_builder import stable_id


@dataclass(frozen=True)
class SubmitFeedbackRequest:
    feedback_type: str
    target_type: str
    target_id: str
    user_id: str | None = None
    content: str | None = None
    weight: float = 1.0
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class SubmitFeedbackResult:
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)


class FeedbackMemoryApplicationService:
    def __init__(self, feedback_service: FeedbackMemoryService) -> None:
        self.feedback_service = feedback_service

    def submit_feedback(self, request: SubmitFeedbackRequest) -> SubmitFeedbackResult:
        feedback = FeedbackMemory(
            feedback_id=self._feedback_id(request),
            feedback_type=request.feedback_type,  # type: ignore[arg-type]
            target_type=request.target_type,
            target_id=request.target_id,
            user_id=request.user_id,
            content=request.content,
            weight=request.weight,
            metadata=dict(request.metadata or {}),
        )
        result = self.feedback_service.ingest_feedback(feedback)
        return SubmitFeedbackResult(result.to_dict())

    def _feedback_id(self, request: SubmitFeedbackRequest) -> str:
        return stable_id(
            "feedback",
            request.feedback_type,
            request.target_type,
            request.target_id,
            request.user_id or "",
            request.content or "",
            prefix="feedback",
        )


__all__ = ["FeedbackMemoryApplicationService", "SubmitFeedbackRequest", "SubmitFeedbackResult"]
