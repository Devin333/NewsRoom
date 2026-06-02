"""Exceptions raised by the shared agent session runtime."""

from __future__ import annotations


class AgentSessionError(RuntimeError):
    """Base error for shared agent session failures."""


class AgentSessionStoreError(AgentSessionError):
    """Raised when a session store operation fails."""


class AgentSessionAccessDenied(AgentSessionError):
    """Raised when an agent attempts an unauthorized session access."""
