from interfaces.services.feedback_memory_service import FeedbackMemoryApplicationService, SubmitFeedbackRequest


def test_feedback_memory_service_submits_stable_feedback_id() -> None:
    feedback_service = _FeedbackService()
    service = FeedbackMemoryApplicationService(feedback_service)
    request = SubmitFeedbackRequest(
        feedback_type="source_block",
        target_type="source",
        target_id="source-1",
        user_id="user-1",
        content="too noisy",
    )

    first = service.submit_feedback(request).to_dict()
    second = service.submit_feedback(request).to_dict()

    assert first["feedback_id"] == second["feedback_id"]
    assert feedback_service.feedback[0].feedback_type == "source_block"
    assert feedback_service.feedback[0].target_id == "source-1"


class _FeedbackService:
    def __init__(self) -> None:
        self.feedback = []

    def ingest_feedback(self, feedback):
        self.feedback.append(feedback)
        return _Result(feedback.feedback_id)


class _Result:
    def __init__(self, feedback_id: str) -> None:
        self.feedback_id = feedback_id

    def to_dict(self):
        return {"feedback_id": self.feedback_id, "preference_ids": ["preference-1"], "decision_ids": []}
