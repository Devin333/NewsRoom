"""Lifecycle manager for shared agent sessions."""

from __future__ import annotations

from typing import Any, Mapping

from framework.agent.session.models import AgentSessionEvent, AgentSessionRef
from framework.agent.session.store import AgentSessionStore


class SessionLifecycleManager:
    """Create and close session lifecycle states with audit events."""

    def __init__(self, store: AgentSessionStore) -> None:
        self._store = store

    def create(self, ref: AgentSessionRef) -> None:
        """Create a session and record its creation event."""

        self._store.create_session(ref)

    def start(self, *, session_id: str, run_id: str) -> None:
        """Record that a session started running."""

        self._store.append_event(AgentSessionEvent(session_id=session_id, run_id=run_id, event_type="session.started"))

    def complete(self, *, session_id: str, metadata: Mapping[str, Any] | None = None) -> None:
        """Close a session as completed."""

        self._store.close_session(session_id=session_id, status="completed", metadata=metadata)

    def fail(self, *, session_id: str, metadata: Mapping[str, Any] | None = None) -> None:
        """Close a session as failed."""

        self._store.close_session(session_id=session_id, status="failed", metadata=metadata)
