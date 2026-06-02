"""Validated workspace API for writing and reading shared agent session items."""

from __future__ import annotations

from dataclasses import replace
from collections.abc import Mapping, Sequence
from typing import Any

from framework.agent.session.access_policy import SessionAccessPolicy
from framework.agent.session.compaction import SessionCompactor
from framework.agent.session.exceptions import AgentSessionAccessDenied
from framework.agent.session.models import AgentSessionEvent, AgentSessionItem, AgentSessionRef, AgentSessionSnapshot, SessionVisibility
from framework.agent.session.query import AgentSessionQuery
from framework.agent.session.sanitization import sanitize_session_content, sanitize_session_content_with_report
from framework.agent.session.store import AgentSessionStore


class AgentSharedWorkspace:
    """High-level API for orchestrators to manage shared agent session state."""

    def __init__(
        self,
        store: AgentSessionStore | None = None,
        *,
        access_policy: SessionAccessPolicy | None = None,
        compactor: SessionCompactor | None = None,
    ) -> None:
        if store is None:
            raise ValueError("store is required")
        self._store = store
        self._access_policy = access_policy or SessionAccessPolicy()
        self._compactor = compactor or SessionCompactor()

    def create_session(self, ref: AgentSessionRef) -> None:
        """Create a shared agent session boundary."""

        self._store.create_session(ref)

    def write(
        self,
        *,
        ref: AgentSessionRef | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
        agent_id: str,
        role: str,
        content: Mapping[str, Any],
        summary: str | None = None,
        confidence: float | None = None,
        visibility: SessionVisibility = SessionVisibility.SHARED,
        refs: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AgentSessionItem:
        """Validate, sanitize, timestamp, and write a session item."""

        session_ref = ref or AgentSessionRef(session_id=str(session_id or ""), run_id=run_id)
        _require_text(session_ref.session_id, "session_id")
        _require_text(agent_id, "agent_id")
        _require_text(role, "role")
        if not self._access_policy.can_write(agent_id=agent_id, role=role):
            raise AgentSessionAccessDenied(f"agent {agent_id} cannot write role {role}")
        if not isinstance(content, Mapping):
            raise TypeError("content must be a Mapping")
        sanitized_content = sanitize_session_content_with_report(content)
        sanitized_refs = sanitize_session_content_with_report(refs or {})
        sanitized_metadata = sanitize_session_content_with_report(metadata or {})
        redacted_fields = (
            sanitized_content.redacted_fields
            + tuple(f"refs.{item}" for item in sanitized_refs.redacted_fields)
            + tuple(f"metadata.{item}" for item in sanitized_metadata.redacted_fields)
        )
        item_metadata = dict(sanitized_metadata.content)
        if redacted_fields:
            item_metadata["redacted_fields"] = list(redacted_fields)
        item = AgentSessionItem(
            session_id=session_ref.session_id,
            run_id=session_ref.run_id or "",
            agent_id=agent_id,
            role=role,
            content=sanitized_content.content,
            summary=summary,
            confidence=confidence,
            visibility=self._access_policy.visibility_for_role(role, SessionVisibility(str(visibility))),
            refs=sanitized_refs.content,
            metadata=item_metadata,
        )
        stored = self._store.append_item(item)
        self._maybe_compact(stored.session_id, stored.run_id)
        return stored

    def read(
        self,
        *,
        session_id: str,
        roles: Sequence[str] | None = None,
        agent_ids: Sequence[str] | None = None,
        limit: int | None = None,
        reader_agent_id: str | None = None,
        include_private: bool = False,
    ) -> tuple[AgentSessionItem, ...]:
        """Read shared items from one session."""

        visibility = tuple(SessionVisibility) if include_private and reader_agent_id else (
            SessionVisibility.PUBLIC,
            SessionVisibility.SHARED,
            SessionVisibility.FINAL,
        )
        items = self._store.query_items(
            AgentSessionQuery(
                session_id=session_id,
                roles=tuple(str(role) for role in (roles or ())),
                agent_ids=tuple(str(agent_id) for agent_id in (agent_ids or ())),
                statuses=(),
                visibility=visibility,
                include_private=include_private and reader_agent_id is not None,
                limit=limit,
            )
        )
        if reader_agent_id is None:
            return tuple(items)
        return tuple(item for item in items if self._access_policy.can_read(agent_id=reader_agent_id, item=item))

    def query(
        self,
        query: AgentSessionQuery,
        *,
        reader_agent_id: str | None = None,
    ) -> tuple[AgentSessionItem, ...]:
        """Read shared items through AgentSessionQuery and access policy."""

        effective_query = _query_visible_to_reader(query, reader_agent_id=reader_agent_id)
        items = self._store.query_items(effective_query)
        if reader_agent_id is None:
            return tuple(items)
        return tuple(item for item in items if self._access_policy.can_read(agent_id=reader_agent_id, item=item))

    def latest(
        self,
        *,
        session_id: str,
        role: str,
        reader_agent_id: str | None = None,
        include_private: bool = False,
    ) -> AgentSessionItem | None:
        """Return the latest item for a role in one session."""

        visibility = tuple(SessionVisibility) if include_private and reader_agent_id else (
            SessionVisibility.PUBLIC,
            SessionVisibility.SHARED,
            SessionVisibility.FINAL,
        )
        items = self.query(
            AgentSessionQuery(
                session_id=session_id,
                roles=(role,),
                statuses=(),
                visibility=visibility,
                include_private=include_private and reader_agent_id is not None,
                limit=1,
            ),
            reader_agent_id=reader_agent_id,
        )
        return items[-1] if items else None

    def mark_final(self, *, session_id: str, item_id: str) -> AgentSessionItem:
        """Mark an item as final and visible to downstream readers."""

        return self._store.update_item(
            session_id=session_id,
            item_id=item_id,
            status="final",
            visibility=SessionVisibility.FINAL.value,
            metadata={"final": True},
        )

    def reject_item(self, *, session_id: str, item_id: str, reason: str) -> AgentSessionItem:
        """Reject an item with a structured reason."""

        return self._store.update_item(session_id=session_id, item_id=item_id, status="rejected", metadata={"rejectionReason": reason})

    def create_snapshot(self, *, session_id: str, run_id: str) -> AgentSessionSnapshot:
        """Create and persist a compact session snapshot."""

        items = self._store.query_items(AgentSessionQuery(session_id=session_id, statuses=(), visibility=tuple(SessionVisibility), include_private=True))
        events = self._store.list_events(session_id=session_id)
        snapshot = self._compactor.compact(session_id=session_id, run_id=run_id, items=items, events=events)
        return self._store.create_snapshot(snapshot)

    def close_session(self, *, session_id: str, status: str, metadata: Mapping[str, Any] | None = None) -> None:
        """Close a session with a terminal status."""

        self._store.close_session(session_id=session_id, status=status, metadata=sanitize_session_content(metadata or {}))

    def clear(self, session_id: str) -> None:
        """Clear all shared items for one session."""

        self._store.clear_session(session_id)

    def append_event(self, event: AgentSessionEvent) -> AgentSessionEvent:
        """Append an explicit session event."""

        return self._store.append_event(event)

    def list_events(self, *, session_id: str, limit: int | None = None) -> tuple[AgentSessionEvent, ...]:
        """List session events."""

        return tuple(self._store.list_events(session_id=session_id, limit=limit))

    def latest_snapshot(self, session_id: str) -> AgentSessionSnapshot | None:
        """Return the latest session snapshot."""

        return self._store.latest_snapshot(session_id)

    def _maybe_compact(self, session_id: str, run_id: str) -> None:
        items = self._store.query_items(AgentSessionQuery(session_id=session_id, statuses=(), visibility=tuple(SessionVisibility), include_private=True))
        if not self._compactor.should_compact(items=items):
            return
        events = self._store.list_events(session_id=session_id)
        self._store.create_snapshot(self._compactor.compact(session_id=session_id, run_id=run_id, items=items, events=events))


def _require_text(value: str, name: str) -> None:
    if not str(value or "").strip():
        raise ValueError(f"{name} is required")


def _query_visible_to_reader(query: AgentSessionQuery, *, reader_agent_id: str | None) -> AgentSessionQuery:
    if query.include_private and reader_agent_id is not None:
        return query
    public_visibility = tuple(item for item in query.visibility if item != SessionVisibility.PRIVATE)
    return replace(query, visibility=public_visibility, include_private=False)
