from __future__ import annotations

from framework.agent.session import AgentSessionEvent, AgentSessionItem, SessionCompactor, SessionVisibility


def test_compactor_keeps_role_summaries_events_and_final_item_refs() -> None:
    final_item = AgentSessionItem(
        item_id="item-final",
        session_id="session-1",
        run_id="run-1",
        agent_id="agent-a",
        role="final",
        content={"large": "content should not be copied"},
        summary="Final answer.",
        status="final",
        visibility=SessionVisibility.FINAL,
    )
    draft_item = AgentSessionItem(
        item_id="item-draft",
        session_id="session-1",
        run_id="run-1",
        agent_id="agent-b",
        role="draft",
        content={"large": "content should not be copied"},
        summary="Draft answer.",
        metadata={"evidenceRefs": [{"id": "evidence-1"}]},
    )
    event = AgentSessionEvent(
        event_id="event-1",
        session_id="session-1",
        run_id="run-1",
        event_type="item.written",
    )

    snapshot = SessionCompactor(max_items_before_compaction=2).compact(
        session_id="session-1",
        run_id="run-1",
        items=[final_item, draft_item],
        events=[event],
    )

    assert snapshot.final_items == ("item-final",)
    assert snapshot.source_event_ids == ("event-1",)
    assert snapshot.role_summaries["final"]["summaries"] == ["Final answer."]
    assert snapshot.role_summaries["draft"]["evidenceRefs"] == [{"id": "evidence-1"}]
    assert "content should not be copied" not in str(snapshot.role_summaries)


def test_compactor_threshold() -> None:
    assert SessionCompactor(max_items_before_compaction=2).should_compact(
        items=[
            AgentSessionItem(session_id="session-1", run_id="run-1", agent_id="a", role="r", content={}),
            AgentSessionItem(session_id="session-1", run_id="run-1", agent_id="b", role="r", content={}),
        ]
    )
