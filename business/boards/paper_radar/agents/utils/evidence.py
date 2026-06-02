"""Shared evidence helpers for paper analysis agents."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from framework.agent.session import AgentSessionItem


def latest_output(items: Sequence[AgentSessionItem], role: str) -> Mapping[str, Any]:
    """Return the latest output content for a role."""

    for item in reversed(items):
        if item.role == role:
            return item.content
    return {}


def sequence(value: Any) -> Sequence[Any]:
    """Return list-like values and hide strings as scalar values."""

    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []


def evidence_excerpt(text: str, *, limit: int = 500) -> str:
    """Return a whitespace-normalized evidence excerpt."""

    return " ".join(str(text or "").split())[:limit]
