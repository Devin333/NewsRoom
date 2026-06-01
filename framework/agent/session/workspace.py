"""Validated workspace API for writing and reading shared agent session items."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from framework.agent.session.models import AgentSessionItem
from framework.agent.session.sanitization import sanitize_session_content
from framework.agent.session.store import AgentSessionStore


class AgentSharedWorkspace:
    """High-level API for orchestrators to manage shared agent session state."""

    def __init__(self, store: AgentSessionStore) -> None:
        self._store = store

    def write(
        self,
        *,
        session_id: str,
        agent_id: str,
        role: str,
        content: Mapping[str, Any],
        summary: str | None = None,
        confidence: float | None = None,
        refs: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AgentSessionItem:
        """Validate, sanitize, timestamp, and write a session item."""

        _require_text(session_id, "session_id")
        _require_text(agent_id, "agent_id")
        _require_text(role, "role")
        if not isinstance(content, Mapping):
            raise TypeError("content must be a Mapping")
        item = AgentSessionItem(
            session_id=session_id,
            agent_id=agent_id,
            role=role,
            content=sanitize_session_content(content),
            summary=summary,
            confidence=confidence,
            refs=sanitize_session_content(refs or {}),
            metadata=sanitize_session_content(metadata or {}),
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._store.write_item(item)
        return item

    def read(
        self,
        *,
        session_id: str,
        roles: Sequence[str] | None = None,
        agent_ids: Sequence[str] | None = None,
        limit: int | None = None,
    ) -> tuple[AgentSessionItem, ...]:
        """Read shared items from one session."""

        return tuple(
            self._store.read_items(
                session_id=session_id,
                roles=roles,
                agent_ids=agent_ids,
                limit=limit,
            )
        )

    def latest(
        self,
        *,
        session_id: str,
        role: str,
    ) -> AgentSessionItem | None:
        """Return the latest item for a role in one session."""

        return self._store.latest_item(session_id=session_id, role=role)

    def clear(self, session_id: str) -> None:
        """Clear all shared items for one session."""

        self._store.clear_session(session_id)


def _require_text(value: str, name: str) -> None:
    if not str(value or "").strip():
        raise ValueError(f"{name} is required")
