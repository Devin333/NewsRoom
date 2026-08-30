from backend.memory.recall_planner import RecallPlanner


def test_entity_id_selects_entity_history() -> None:
    plan = RecallPlanner().plan("anything", entity_id="entity-1")

    assert plan.intent == "entity_history"
    assert plan.target_type == "entity"
    assert plan.target_id == "entity-1"


def test_claim_text_selects_claim_check() -> None:
    plan = RecallPlanner().plan("check", claim_text="OpenAI released a model")

    assert plan.intent == "claim_check"


def test_source_id_selects_source_reliability() -> None:
    plan = RecallPlanner().plan("source", source_id="source-1")

    assert plan.intent == "source_reliability"
    assert plan.target_type == "source"


def test_history_query_selects_topic_overview() -> None:
    plan = RecallPlanner().plan("show timeline history", topic="AI")

    assert plan.intent == "topic_overview"
    assert plan.topic == "AI"
