from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from framework.agent.session import (
    AgentSessionItem,
    AgentSessionQuery,
    AgentSessionRef,
    AgentSessionSnapshot,
    SQLiteAgentSessionStore,
    SessionVisibility,
)


def test_sqlite_store_persists_items_events_snapshots_and_updates(tmp_path) -> None:
    store = SQLiteAgentSessionStore(tmp_path / "sessions.sqlite3")
    ref = AgentSessionRef(session_id="session-1", run_id="run-1", workflow_id="workflow")

    store.create_session(ref)
    item = store.append_item(
        AgentSessionItem(
            session_id="session-1",
            run_id="run-1",
            agent_id="agent-a",
            role="decision",
            content={"answer": "yes"},
            summary="Agent decided yes.",
            confidence=0.9,
        )
    )
    store.append_item(
        AgentSessionItem(
            session_id="session-2",
            run_id="run-2",
            agent_id="agent-b",
            role="decision",
            content={"answer": "no"},
        )
    )

    queried = store.query_items(AgentSessionQuery(session_id="session-1", roles=("decision",)))
    assert [found.item_id for found in queried] == [item.item_id]
    assert store.latest_item(session_id="session-1", role="decision", status="*").content == {"answer": "yes"}

    updated = store.update_item(session_id="session-1", item_id=item.item_id, status="final", metadata={"final": True})
    assert updated.status == "final"
    assert updated.version == 2

    snapshot = store.create_snapshot(
        AgentSessionSnapshot(
            session_id="session-1",
            run_id="run-1",
            summary="decision: 1",
            role_summaries={"decision": {"count": 1}},
            final_items=(item.item_id,),
            source_event_ids=(),
        )
    )
    assert store.latest_snapshot("session-1").snapshot_id == snapshot.snapshot_id

    store.close_session(session_id="session-1", status="completed", metadata={"paperId": "paper-1"})
    event_types = [event.event_type for event in store.list_events(session_id="session-1")]
    assert event_types == [
        "session.created",
        "item.written",
        "item.updated",
        "snapshot.created",
        "session.completed",
    ]
    assert store.query_items(AgentSessionQuery(session_id="session-2", visibility=tuple(SessionVisibility), include_private=True))


def test_sqlite_store_can_reopen_existing_session_database(tmp_path) -> None:
    path = tmp_path / "sessions.sqlite3"
    first = SQLiteAgentSessionStore(path)
    first.create_session(AgentSessionRef(session_id="session-1", run_id="run-1"))
    first.append_item(
        AgentSessionItem(
            session_id="session-1",
            run_id="run-1",
            agent_id="agent-a",
            role="note",
            content={"value": 1},
        )
    )
    first.close()

    second = SQLiteAgentSessionStore(path)
    assert second.latest_item(session_id="session-1", role="note", status="*").content == {"value": 1}


def test_sqlite_store_supports_shared_connection_across_threads(tmp_path) -> None:
    store = SQLiteAgentSessionStore(tmp_path / "sessions.sqlite3")
    store.create_session(AgentSessionRef(session_id="threaded-session", run_id="run-1"))

    def append(index: int) -> str:
        return store.append_item(
            AgentSessionItem(
                session_id="threaded-session",
                run_id="run-1",
                agent_id=f"agent-{index % 4}",
                role="note",
                content={"index": index},
            )
        ).item_id

    with ThreadPoolExecutor(max_workers=8) as executor:
        item_ids = list(executor.map(append, range(30)))

    items = store.query_items(AgentSessionQuery(session_id="threaded-session", roles=("note",)))
    event_types = [event.event_type for event in store.list_events(session_id="threaded-session")]

    assert len(set(item_ids)) == 30
    assert len(items) == 30
    assert event_types.count("item.written") == 30
