from __future__ import annotations

from framework.agent.session import AgentSessionItem, InMemoryAgentSessionStore


def _item(session_id: str, role: str, agent_id: str = "agent-a") -> AgentSessionItem:
    return AgentSessionItem(session_id=session_id, agent_id=agent_id, role=role, content={"value": role})


def test_store_writes_and_reads_items() -> None:
    store = InMemoryAgentSessionStore()
    store.write_item(_item("session-1", "observation"))

    items = store.read_items(session_id="session-1")

    assert len(items) == 1
    assert items[0].content == {"value": "observation"}


def test_store_filters_by_role() -> None:
    store = InMemoryAgentSessionStore()
    store.write_item(_item("session-1", "observation"))
    store.write_item(_item("session-1", "decision"))

    items = store.read_items(session_id="session-1", roles=["decision"])

    assert [item.role for item in items] == ["decision"]


def test_store_filters_by_agent_id() -> None:
    store = InMemoryAgentSessionStore()
    store.write_item(_item("session-1", "observation", agent_id="agent-a"))
    store.write_item(_item("session-1", "observation", agent_id="agent-b"))

    items = store.read_items(session_id="session-1", agent_ids=["agent-b"])

    assert [item.agent_id for item in items] == ["agent-b"]


def test_store_isolates_sessions_and_clears_only_requested_session() -> None:
    store = InMemoryAgentSessionStore()
    store.write_item(_item("session-1", "observation"))
    store.write_item(_item("session-2", "observation"))

    store.clear_session("session-1")

    assert store.read_items(session_id="session-1") == []
    assert len(store.read_items(session_id="session-2")) == 1


def test_store_returns_latest_item_and_limit() -> None:
    store = InMemoryAgentSessionStore()
    store.write_item(_item("session-1", "decision", agent_id="agent-a"))
    store.write_item(_item("session-1", "observation", agent_id="agent-b"))
    store.write_item(_item("session-1", "decision", agent_id="agent-c"))

    latest = store.latest_item(session_id="session-1", role="decision")
    limited = store.read_items(session_id="session-1", limit=2)

    assert latest is not None
    assert latest.agent_id == "agent-c"
    assert [item.agent_id for item in limited] == ["agent-b", "agent-c"]
