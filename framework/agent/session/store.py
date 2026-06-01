"""Session store protocol and in-memory implementation for shared agent workspaces."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from framework.agent.session.models import AgentSessionItem


class AgentSessionStore(Protocol):
    """Persistence interface for generic agent session items."""

    def write_item(self, item: AgentSessionItem) -> None:
        """Write one item into the store."""
        ...

    def read_items(
        self,
        *,
        session_id: str,
        roles: Sequence[str] | None = None,
        agent_ids: Sequence[str] | None = None,
        limit: int | None = None,
    ) -> list[AgentSessionItem]:
        """Read items for one session, optionally filtered by role or agent id."""
        ...

    def latest_item(
        self,
        *,
        session_id: str,
        role: str,
    ) -> AgentSessionItem | None:
        """Return the latest item matching a role in a session."""
        ...

    def clear_session(self, session_id: str) -> None:
        """Clear all items for one session."""
        ...


class InMemoryAgentSessionStore:
    """Process-local session store isolated by session id."""

    def __init__(self) -> None:
        self._items_by_session: dict[str, list[AgentSessionItem]] = {}

    def write_item(self, item: AgentSessionItem) -> None:
        self._items_by_session.setdefault(item.session_id, []).append(item)

    def read_items(
        self,
        *,
        session_id: str,
        roles: Sequence[str] | None = None,
        agent_ids: Sequence[str] | None = None,
        limit: int | None = None,
    ) -> list[AgentSessionItem]:
        items = list(self._items_by_session.get(session_id, []))
        if roles is not None:
            role_set = {str(role) for role in roles}
            items = [item for item in items if item.role in role_set]
        if agent_ids is not None:
            agent_id_set = {str(agent_id) for agent_id in agent_ids}
            items = [item for item in items if item.agent_id in agent_id_set]
        if limit is not None and limit >= 0:
            items = items[-limit:] if limit else []
        return items

    def latest_item(
        self,
        *,
        session_id: str,
        role: str,
    ) -> AgentSessionItem | None:
        for item in reversed(self._items_by_session.get(session_id, [])):
            if item.role == role:
                return item
        return None

    def clear_session(self, session_id: str) -> None:
        self._items_by_session.pop(session_id, None)
