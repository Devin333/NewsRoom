"""In-memory session store for tests and local deterministic workflows."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from framework.agent.session.models import AgentSessionEvent, AgentSessionItem, AgentSessionRef, AgentSessionSnapshot, SessionVisibility
from framework.agent.session.query import AgentSessionQuery


class InMemoryAgentSessionStore:
    """Process-local session store isolated by session id."""

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}
        self._items_by_session: dict[str, list[AgentSessionItem]] = {}
        self._events_by_session: dict[str, list[AgentSessionEvent]] = {}
        self._snapshots_by_session: dict[str, list[AgentSessionSnapshot]] = {}

    def create_session(self, ref: AgentSessionRef) -> None:
        now = _now()
        existing = self._sessions.get(ref.session_id, {})
        self._sessions[ref.session_id] = {
            **existing,
            **ref.to_refs(),
            "status": existing.get("status") or "created",
            "created_at": existing.get("created_at") or now,
            "updated_at": now,
            "metadata": existing.get("metadata") or {},
        }
        if not any(event.event_type == "session.created" for event in self._events_by_session.get(ref.session_id, [])):
            self.append_event(
                AgentSessionEvent(
                    session_id=ref.session_id,
                    run_id=ref.run_id or "",
                    event_type="session.created",
                    payload=ref.to_refs(),
                )
            )

    def append_item(self, item: AgentSessionItem) -> AgentSessionItem:
        stored = _with_times(item)
        self._items_by_session.setdefault(stored.session_id, []).append(stored)
        self.append_event(
            AgentSessionEvent(
                session_id=stored.session_id,
                run_id=stored.run_id,
                event_type="item.written",
                agent_id=stored.agent_id,
                item_id=stored.item_id,
                role=stored.role,
                payload={"status": stored.status, "visibility": stored.visibility.value},
            )
        )
        return stored

    def write_item(self, item: AgentSessionItem) -> None:
        """Backward-compatible alias for append_item."""

        self.append_item(item)

    def update_item(
        self,
        *,
        session_id: str,
        item_id: str,
        status: str | None = None,
        content: Mapping[str, object] | None = None,
        summary: str | None = None,
        metadata: Mapping[str, object] | None = None,
        visibility: str | None = None,
    ) -> AgentSessionItem:
        items = self._items_by_session.get(session_id, [])
        for index, item in enumerate(items):
            if item.item_id != item_id:
                continue
            updated = replace(
                item,
                status=status or item.status,
                content=content if content is not None else item.content,
                summary=summary if summary is not None else item.summary,
                metadata={**dict(item.metadata), **dict(metadata or {})},
                visibility=SessionVisibility(str(visibility)) if visibility is not None else item.visibility,
                updated_at=_now(),
                version=item.version + 1,
            )
            items[index] = updated
            self.append_event(
                AgentSessionEvent(
                    session_id=session_id,
                    run_id=updated.run_id,
                    event_type="item.updated",
                    agent_id=updated.agent_id,
                    item_id=item_id,
                    role=updated.role,
                    payload={"status": updated.status, "visibility": updated.visibility.value},
                )
            )
            return updated
        raise KeyError(f"session item not found: {session_id}/{item_id}")

    def query_items(self, query: AgentSessionQuery) -> list[AgentSessionItem]:
        items = list(self._items_by_session.get(query.session_id, []))
        if query.roles:
            items = [item for item in items if item.role in set(query.roles)]
        if query.agent_ids:
            items = [item for item in items if item.agent_id in set(query.agent_ids)]
        if query.statuses:
            items = [item for item in items if item.status in set(query.statuses)]
        visibility = set(query.visibility)
        if query.include_private:
            visibility.add(SessionVisibility.PRIVATE)
        items = [item for item in items if item.visibility in visibility]
        if query.refs:
            items = [item for item in items if _refs_match(item.refs, query.refs)]
        if not query.include_content:
            items = [replace(item, content={}) for item in items]
        if query.limit is not None and query.limit >= 0:
            items = items[-query.limit :] if query.limit else []
        return items

    def read_items(
        self,
        *,
        session_id: str,
        roles: Sequence[str] | None = None,
        agent_ids: Sequence[str] | None = None,
        limit: int | None = None,
    ) -> list[AgentSessionItem]:
        """Backward-compatible read API."""

        return self.query_items(
            AgentSessionQuery(
                session_id=session_id,
                roles=tuple(str(role) for role in (roles or ())),
                agent_ids=tuple(str(agent_id) for agent_id in (agent_ids or ())),
                limit=limit,
                include_private=True,
                visibility=tuple(SessionVisibility),
                statuses=(),
            )
        )

    def latest_item(
        self,
        *,
        session_id: str,
        role: str,
        status: str = "active",
    ) -> AgentSessionItem | None:
        statuses = () if status == "*" else (status,)
        for item in reversed(self.query_items(AgentSessionQuery(session_id=session_id, roles=(role,), statuses=statuses, visibility=tuple(SessionVisibility), include_private=True))):
            return item
        return None

    def append_event(self, event: AgentSessionEvent) -> AgentSessionEvent:
        stored = event if event.created_at else replace(event, created_at=_now())
        self._events_by_session.setdefault(stored.session_id, []).append(stored)
        return stored

    def list_events(self, *, session_id: str, limit: int | None = None) -> list[AgentSessionEvent]:
        events = list(self._events_by_session.get(session_id, []))
        if limit is not None and limit >= 0:
            events = events[-limit:] if limit else []
        return events

    def create_snapshot(self, snapshot: AgentSessionSnapshot) -> AgentSessionSnapshot:
        stored = snapshot if snapshot.created_at else replace(snapshot, created_at=_now())
        self._snapshots_by_session.setdefault(stored.session_id, []).append(stored)
        self.append_event(
            AgentSessionEvent(
                session_id=stored.session_id,
                run_id=stored.run_id,
                event_type="snapshot.created",
                payload={"snapshot_id": stored.snapshot_id},
            )
        )
        return stored

    def latest_snapshot(self, session_id: str) -> AgentSessionSnapshot | None:
        snapshots = self._snapshots_by_session.get(session_id, [])
        return snapshots[-1] if snapshots else None

    def close_session(self, *, session_id: str, status: str, metadata: Mapping[str, object] | None = None) -> None:
        session = self._sessions.setdefault(session_id, {"created_at": _now()})
        session.update({"status": status, "updated_at": _now(), "metadata": dict(metadata or {})})
        run_id = str(session.get("run_id") or "")
        event_type = "session.completed" if status == "completed" else "session.failed" if status == "failed" else f"session.{status}"
        self.append_event(AgentSessionEvent(session_id=session_id, run_id=run_id, event_type=event_type, payload=dict(metadata or {})))

    def clear_session(self, session_id: str) -> None:
        """Backward-compatible test helper for clearing a session."""

        self._items_by_session.pop(session_id, None)
        self._events_by_session.pop(session_id, None)
        self._snapshots_by_session.pop(session_id, None)
        self._sessions.pop(session_id, None)


def _with_times(item: AgentSessionItem) -> AgentSessionItem:
    now = _now()
    return replace(
        item,
        created_at=item.created_at or now,
        updated_at=item.updated_at or item.created_at or now,
    )


def _refs_match(actual: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    return all(actual.get(key) == value for key, value in expected.items())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
