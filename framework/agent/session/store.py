"""Session store protocol for shared agent workspaces."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from framework.agent.session.models import AgentSessionEvent, AgentSessionItem, AgentSessionRef, AgentSessionSnapshot
from framework.agent.session.query import AgentSessionQuery


class AgentSessionStore(Protocol):
    """Persistence interface for generic agent session state."""

    def create_session(self, ref: AgentSessionRef) -> None:
        """Create or update one session boundary."""
        ...

    def append_item(self, item: AgentSessionItem) -> AgentSessionItem:
        """Append one item into the store and record an event."""
        ...

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
        """Update mutable item fields and record an event."""
        ...

    def query_items(self, query: AgentSessionQuery) -> list[AgentSessionItem]:
        """Read items through the structured query model."""
        ...

    def latest_item(
        self,
        *,
        session_id: str,
        role: str,
        status: str = "active",
    ) -> AgentSessionItem | None:
        """Return the latest item matching a role in a session."""
        ...

    def append_event(self, event: AgentSessionEvent) -> AgentSessionEvent:
        """Append an audit event."""
        ...

    def list_events(
        self,
        *,
        session_id: str,
        limit: int | None = None,
    ) -> list[AgentSessionEvent]:
        """List session events."""
        ...

    def create_snapshot(self, snapshot: AgentSessionSnapshot) -> AgentSessionSnapshot:
        """Persist one session snapshot."""
        ...

    def latest_snapshot(self, session_id: str) -> AgentSessionSnapshot | None:
        """Return the latest snapshot for one session."""
        ...

    def close_session(
        self,
        *,
        session_id: str,
        status: str,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        """Close a session with a terminal status."""
        ...


from framework.agent.session.in_memory_store import InMemoryAgentSessionStore

__all__ = ["AgentSessionStore", "InMemoryAgentSessionStore"]
