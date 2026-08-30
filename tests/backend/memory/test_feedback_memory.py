from backend.memory.feedback_memory import (
    FeedbackMemory,
    FeedbackMemoryService,
    estimate_previous_misrank_penalty,
)
from backend.memory.models import BusinessMemoryHit


def test_feedback_memory_converts_source_feedback_to_preference() -> None:
    repository = _FeedbackRepository()
    service = FeedbackMemoryService(repository)
    feedback = FeedbackMemory(
        feedback_id="fb-1",
        feedback_type="source_block",
        target_type="source",
        target_id="source-1",
        content="Too noisy for this board",
        weight=-1.0,
        user_id="user-1",
    )

    result = service.ingest_feedback(feedback)

    assert result.preference_ids
    assert not result.decision_ids
    assert repository.preferences[0].owner_type == "source"
    assert repository.preferences[0].owner_id == "source-1"
    assert repository.preferences[0].source == "human_feedback"
    assert repository.preferences[0].metadata["feedback_type"] == "source_block"


def test_feedback_memory_converts_correction_to_decision() -> None:
    repository = _FeedbackRepository()
    service = FeedbackMemoryService(repository)
    feedback = FeedbackMemory(
        feedback_id="fb-2",
        feedback_type="claim_correction",
        target_type="claim",
        target_id="claim-1",
        content="This claim was later corrected.",
        metadata={"run_id": "run-1"},
    )

    result = service.ingest_feedback(feedback)

    assert not result.preference_ids
    assert result.decision_ids
    assert repository.decisions[0].decision == "correction"
    assert repository.decisions[0].run_id == "run-1"
    assert repository.decisions[0].target_id == "claim-1"


def test_previous_misrank_penalty_is_preserved() -> None:
    hit = BusinessMemoryHit(
        hit_id="memory-1",
        text="A weak item",
        score=0.7,
        tags=["weak_evidence_ranked_too_high"],
        metadata={"note": "community_noise_overranked"},
    )

    assert estimate_previous_misrank_penalty([hit]) > 0.0


class _FeedbackRepository:
    def __init__(self) -> None:
        self.preferences = []
        self.decisions = []

    def save_preferences(self, preferences):
        self.preferences.extend(preferences)

    def save_decisions(self, decisions):
        self.decisions.extend(decisions)
