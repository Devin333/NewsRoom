from __future__ import annotations

from framework.agent.session import AgentSessionRef, InMemoryAgentSessionStore, SessionLifecycleManager


def test_lifecycle_manager_records_session_events() -> None:
    store = InMemoryAgentSessionStore()
    lifecycle = SessionLifecycleManager(store)

    lifecycle.create(AgentSessionRef(session_id="session-1", run_id="run-1"))
    lifecycle.start(session_id="session-1", run_id="run-1")
    lifecycle.complete(session_id="session-1", metadata={"paperId": "paper-1"})

    assert [event.event_type for event in store.list_events(session_id="session-1")] == [
        "session.created",
        "session.started",
        "session.completed",
    ]


def test_lifecycle_manager_records_failed_session() -> None:
    store = InMemoryAgentSessionStore()
    lifecycle = SessionLifecycleManager(store)

    lifecycle.create(AgentSessionRef(session_id="session-1", run_id="run-1"))
    lifecycle.fail(session_id="session-1", metadata={"reason": "boom"})

    assert store.list_events(session_id="session-1")[-1].event_type == "session.failed"
