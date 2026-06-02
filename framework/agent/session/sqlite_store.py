"""SQLite-backed durable store for shared agent sessions."""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from framework.agent.session.exceptions import AgentSessionStoreError
from framework.agent.session.models import AgentSessionEvent, AgentSessionItem, AgentSessionRef, AgentSessionSnapshot, SessionVisibility
from framework.agent.session.query import AgentSessionQuery


class SQLiteAgentSessionStore:
    """Durable SQLite implementation of the agent session store protocol."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._initialize()

    def create_session(self, ref: AgentSessionRef) -> None:
        now = _now()
        with self._lock, self._conn:
            self._conn.execute(
                """
                insert into agent_sessions (
                  session_id, run_id, workflow_id, parent_agent_id, task_id,
                  tenant_id, user_id, status, created_at, updated_at, metadata_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(session_id) do update set
                  run_id=excluded.run_id,
                  workflow_id=excluded.workflow_id,
                  parent_agent_id=excluded.parent_agent_id,
                  task_id=excluded.task_id,
                  tenant_id=excluded.tenant_id,
                  user_id=excluded.user_id,
                  updated_at=excluded.updated_at
                """,
                (
                    ref.session_id,
                    ref.run_id or "",
                    ref.workflow_id,
                    ref.parent_agent_id,
                    ref.task_id,
                    ref.tenant_id,
                    ref.user_id,
                    "created",
                    now,
                    now,
                    "{}",
                ),
            )
            if not self._has_event(ref.session_id, "session.created"):
                self._append_event_no_transaction(
                    AgentSessionEvent(
                        session_id=ref.session_id,
                        run_id=ref.run_id or "",
                        event_type="session.created",
                        payload=ref.to_refs(),
                    )
                )

    def append_item(self, item: AgentSessionItem) -> AgentSessionItem:
        stored = _with_times(item)
        try:
            content_json = _json(stored.content)
            refs_json = _json(stored.refs)
            metadata_json = _json(stored.metadata)
        except TypeError as exc:
            raise AgentSessionStoreError(f"failed to serialize session item JSON: {exc}") from exc
        with self._lock, self._conn:
            self._conn.execute(
                """
                insert into agent_session_items (
                  item_id, session_id, run_id, agent_id, role, content_json,
                  summary, confidence, visibility, refs_json, metadata_json,
                  status, version, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stored.item_id,
                    stored.session_id,
                    stored.run_id,
                    stored.agent_id,
                    stored.role,
                    content_json,
                    stored.summary,
                    stored.confidence,
                    stored.visibility.value,
                    refs_json,
                    metadata_json,
                    stored.status,
                    stored.version,
                    stored.created_at,
                    stored.updated_at,
                ),
            )
            self._append_event_no_transaction(
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
        with self._lock:
            current = self._get_item(session_id=session_id, item_id=item_id)
            if current is None:
                raise KeyError(f"session item not found: {session_id}/{item_id}")
            updated = replace(
                current,
                status=status or current.status,
                content=content if content is not None else current.content,
                summary=summary if summary is not None else current.summary,
                metadata={**dict(current.metadata), **dict(metadata or {})},
                visibility=SessionVisibility(str(visibility)) if visibility is not None else current.visibility,
                updated_at=_now(),
                version=current.version + 1,
            )
            try:
                content_json = _json(updated.content)
                metadata_json = _json(updated.metadata)
            except TypeError as exc:
                raise AgentSessionStoreError(f"failed to serialize updated session item JSON: {exc}") from exc
            with self._conn:
                self._conn.execute(
                    """
                    update agent_session_items
                       set content_json=?, summary=?, metadata_json=?, status=?, visibility=?, version=?, updated_at=?
                     where session_id=? and item_id=?
                    """,
                    (
                        content_json,
                        updated.summary,
                        metadata_json,
                        updated.status,
                        updated.visibility.value,
                        updated.version,
                        updated.updated_at,
                        session_id,
                        item_id,
                    ),
                )
                self._append_event_no_transaction(
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

    def query_items(self, query: AgentSessionQuery) -> list[AgentSessionItem]:
        clauses = ["session_id = ?"]
        params: list[Any] = [query.session_id]
        if query.roles:
            clauses.append(f"role in ({','.join('?' for _ in query.roles)})")
            params.extend(query.roles)
        if query.agent_ids:
            clauses.append(f"agent_id in ({','.join('?' for _ in query.agent_ids)})")
            params.extend(query.agent_ids)
        if query.statuses:
            clauses.append(f"status in ({','.join('?' for _ in query.statuses)})")
            params.extend(query.statuses)
        visibility = set(query.visibility)
        if query.include_private:
            visibility.add(SessionVisibility.PRIVATE)
        if visibility:
            visibility_values = tuple(item.value for item in visibility)
            clauses.append(f"visibility in ({','.join('?' for _ in visibility_values)})")
            params.extend(visibility_values)
        sql = f"select * from agent_session_items where {' and '.join(clauses)} order by created_at asc, rowid asc"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        items = [_item_from_row(row) for row in rows]
        if query.refs:
            items = [item for item in items if _refs_match(item.refs, query.refs)]
        if not query.include_content:
            items = [replace(item, content={}) for item in items]
        if query.limit is not None and query.limit >= 0:
            items = items[-query.limit :] if query.limit else []
        return items

    def read_items(self, *, session_id: str, roles: tuple[str, ...] | list[str] | None = None, agent_ids: tuple[str, ...] | list[str] | None = None, limit: int | None = None) -> list[AgentSessionItem]:
        """Backward-compatible read API."""

        return self.query_items(
            AgentSessionQuery(
                session_id=session_id,
                roles=tuple(str(role) for role in (roles or ())),
                agent_ids=tuple(str(agent_id) for agent_id in (agent_ids or ())),
                statuses=(),
                visibility=tuple(SessionVisibility),
                include_private=True,
                limit=limit,
            )
        )

    def latest_item(self, *, session_id: str, role: str, status: str = "active") -> AgentSessionItem | None:
        statuses = () if status == "*" else (status,)
        items = self.query_items(
            AgentSessionQuery(
                session_id=session_id,
                roles=(role,),
                statuses=statuses,
                visibility=tuple(SessionVisibility),
                include_private=True,
                limit=1,
            )
        )
        return items[-1] if items else None

    def append_event(self, event: AgentSessionEvent) -> AgentSessionEvent:
        stored = event if event.created_at else replace(event, created_at=_now())
        with self._lock, self._conn:
            self._append_event_no_transaction(stored)
        return stored

    def list_events(self, *, session_id: str, limit: int | None = None) -> list[AgentSessionEvent]:
        sql = "select * from agent_session_events where session_id=? order by created_at asc, rowid asc"
        params: list[Any] = [session_id]
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        events = [_event_from_row(row) for row in rows]
        if limit is not None and limit >= 0:
            events = events[-limit:] if limit else []
        return events

    def create_snapshot(self, snapshot: AgentSessionSnapshot) -> AgentSessionSnapshot:
        stored = snapshot if snapshot.created_at else replace(snapshot, created_at=_now())
        try:
            role_summaries_json = _json(stored.role_summaries)
            final_items_json = _json(stored.final_items)
            source_event_ids_json = _json(stored.source_event_ids)
        except TypeError as exc:
            raise AgentSessionStoreError(f"failed to serialize session snapshot JSON: {exc}") from exc
        with self._lock, self._conn:
            self._conn.execute(
                """
                insert into agent_session_snapshots (
                  snapshot_id, session_id, run_id, summary, role_summaries_json,
                  final_items_json, source_event_ids_json, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stored.snapshot_id,
                    stored.session_id,
                    stored.run_id,
                    stored.summary,
                    role_summaries_json,
                    final_items_json,
                    source_event_ids_json,
                    stored.created_at,
                ),
            )
            self._append_event_no_transaction(
                AgentSessionEvent(
                    session_id=stored.session_id,
                    run_id=stored.run_id,
                    event_type="snapshot.created",
                    payload={"snapshot_id": stored.snapshot_id},
                )
            )
        return stored

    def latest_snapshot(self, session_id: str) -> AgentSessionSnapshot | None:
        with self._lock:
            row = self._conn.execute(
                "select * from agent_session_snapshots where session_id=? order by created_at desc, rowid desc limit 1",
                (session_id,),
            ).fetchone()
        return _snapshot_from_row(row) if row is not None else None

    def close_session(self, *, session_id: str, status: str, metadata: Mapping[str, object] | None = None) -> None:
        metadata_json = _json(dict(metadata or {}))
        now = _now()
        with self._lock:
            row = self._conn.execute("select run_id from agent_sessions where session_id=?", (session_id,)).fetchone()
            run_id = str(row["run_id"]) if row is not None else ""
        event_type = "session.completed" if status == "completed" else "session.failed" if status == "failed" else f"session.{status}"
        with self._lock, self._conn:
            self._conn.execute(
                "update agent_sessions set status=?, updated_at=?, metadata_json=? where session_id=?",
                (status, now, metadata_json, session_id),
            )
            self._append_event_no_transaction(AgentSessionEvent(session_id=session_id, run_id=run_id, event_type=event_type, payload=dict(metadata or {})))

    def clear_session(self, session_id: str) -> None:
        """Backward-compatible test helper for clearing a session."""

        with self._lock, self._conn:
            self._conn.execute("delete from agent_session_items where session_id=?", (session_id,))
            self._conn.execute("delete from agent_session_events where session_id=?", (session_id,))
            self._conn.execute("delete from agent_session_snapshots where session_id=?", (session_id,))
            self._conn.execute("delete from agent_sessions where session_id=?", (session_id,))

    def close(self) -> None:
        """Close the SQLite connection."""

        with self._lock:
            self._conn.close()

    def _append_event_no_transaction(self, event: AgentSessionEvent) -> AgentSessionEvent:
        stored = event if event.created_at else replace(event, created_at=_now())
        try:
            payload_json = _json(stored.payload)
        except TypeError as exc:
            raise AgentSessionStoreError(f"failed to serialize session event JSON: {exc}") from exc
        self._conn.execute(
            """
            insert into agent_session_events (
              event_id, session_id, run_id, event_type, agent_id, item_id, role,
              payload_json, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                stored.event_id,
                stored.session_id,
                stored.run_id,
                stored.event_type,
                stored.agent_id,
                stored.item_id,
                stored.role,
                payload_json,
                stored.created_at,
            ),
        )
        return stored

    def _get_item(self, *, session_id: str, item_id: str) -> AgentSessionItem | None:
        with self._lock:
            row = self._conn.execute(
                "select * from agent_session_items where session_id=? and item_id=?",
                (session_id, item_id),
            ).fetchone()
        return _item_from_row(row) if row is not None else None

    def _has_event(self, session_id: str, event_type: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "select 1 from agent_session_events where session_id=? and event_type=? limit 1",
                (session_id, event_type),
            ).fetchone()
        return row is not None

    def _initialize(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                create table if not exists agent_sessions(
                  session_id text primary key,
                  run_id text not null,
                  workflow_id text,
                  parent_agent_id text,
                  task_id text,
                  tenant_id text,
                  user_id text,
                  status text not null,
                  created_at text not null,
                  updated_at text not null,
                  metadata_json text
                );
                create table if not exists agent_session_items(
                  item_id text primary key,
                  session_id text not null,
                  run_id text not null,
                  agent_id text not null,
                  role text not null,
                  content_json text not null,
                  summary text,
                  confidence real,
                  visibility text not null,
                  refs_json text not null,
                  metadata_json text not null,
                  status text not null,
                  version integer not null,
                  created_at text not null,
                  updated_at text not null
                );
                create table if not exists agent_session_events(
                  event_id text primary key,
                  session_id text not null,
                  run_id text not null,
                  event_type text not null,
                  agent_id text,
                  item_id text,
                  role text,
                  payload_json text not null,
                  created_at text not null
                );
                create table if not exists agent_session_snapshots(
                  snapshot_id text primary key,
                  session_id text not null,
                  run_id text not null,
                  summary text not null,
                  role_summaries_json text not null,
                  final_items_json text not null,
                  source_event_ids_json text not null,
                  created_at text not null
                );
                create index if not exists idx_agent_session_items_session_role on agent_session_items(session_id, role);
                create index if not exists idx_agent_session_items_session_agent on agent_session_items(session_id, agent_id);
                create index if not exists idx_agent_session_items_session_status on agent_session_items(session_id, status);
                create index if not exists idx_agent_session_events_session_created on agent_session_events(session_id, created_at);
                create index if not exists idx_agent_session_snapshots_session_created on agent_session_snapshots(session_id, created_at);
                """
            )


def _item_from_row(row: sqlite3.Row) -> AgentSessionItem:
    return AgentSessionItem(
        item_id=str(row["item_id"]),
        session_id=str(row["session_id"]),
        run_id=str(row["run_id"]),
        agent_id=str(row["agent_id"]),
        role=str(row["role"]),
        content=_loads(row["content_json"]),
        summary=row["summary"],
        confidence=row["confidence"],
        visibility=SessionVisibility(str(row["visibility"])),
        refs=_loads(row["refs_json"]),
        metadata=_loads(row["metadata_json"]),
        status=str(row["status"]),
        version=int(row["version"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _event_from_row(row: sqlite3.Row) -> AgentSessionEvent:
    return AgentSessionEvent(
        event_id=str(row["event_id"]),
        session_id=str(row["session_id"]),
        run_id=str(row["run_id"]),
        event_type=str(row["event_type"]),
        agent_id=row["agent_id"],
        item_id=row["item_id"],
        role=row["role"],
        payload=_loads(row["payload_json"]),
        created_at=str(row["created_at"]),
    )


def _snapshot_from_row(row: sqlite3.Row) -> AgentSessionSnapshot:
    return AgentSessionSnapshot(
        snapshot_id=str(row["snapshot_id"]),
        session_id=str(row["session_id"]),
        run_id=str(row["run_id"]),
        summary=str(row["summary"]),
        role_summaries=_loads(row["role_summaries_json"]),
        final_items=tuple(str(item) for item in _loads(row["final_items_json"])),
        source_event_ids=tuple(str(item) for item in _loads(row["source_event_ids_json"])),
        created_at=str(row["created_at"]),
    )


def _with_times(item: AgentSessionItem) -> AgentSessionItem:
    now = _now()
    return replace(item, created_at=item.created_at or now, updated_at=item.updated_at or item.created_at or now)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _loads(value: str) -> Any:
    return json.loads(value or "{}")


def _refs_match(actual: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    return all(actual.get(key) == value for key, value in expected.items())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
