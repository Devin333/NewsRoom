"""Framework shared session APIs for coordinated agent workflows."""

from framework.agent.session.access_policy import SessionAccessPolicy, SessionRoleSpec
from framework.agent.session.assembler import SharedSessionContextAssembler
from framework.agent.session.artifacts import SessionArtifactRef
from framework.agent.session.compaction import SessionCompactor
from framework.agent.session.exceptions import AgentSessionAccessDenied, AgentSessionError, AgentSessionStoreError
from framework.agent.session.in_memory_store import InMemoryAgentSessionStore
from framework.agent.session.lifecycle import SessionLifecycleManager
from framework.agent.session.memory_store import MemoryRuntimeAgentSessionStore
from framework.agent.session.models import (
    AgentSessionContext,
    AgentSessionEvent,
    AgentSessionItem,
    AgentSessionRef,
    AgentSessionSnapshot,
    SessionVisibility,
)
from framework.agent.session.query import AgentSessionQuery
from framework.agent.session.sanitization import sanitize_session_content, sanitize_session_content_with_report
from framework.agent.session.sqlite_store import SQLiteAgentSessionStore
from framework.agent.session.store import AgentSessionStore
from framework.agent.session.workspace import AgentSharedWorkspace

__all__ = [
    "AgentSessionAccessDenied",
    "AgentSessionContext",
    "AgentSessionError",
    "AgentSessionEvent",
    "AgentSessionItem",
    "AgentSessionRef",
    "AgentSessionQuery",
    "AgentSessionSnapshot",
    "AgentSessionStoreError",
    "AgentSessionStore",
    "InMemoryAgentSessionStore",
    "MemoryRuntimeAgentSessionStore",
    "SQLiteAgentSessionStore",
    "AgentSharedWorkspace",
    "SessionAccessPolicy",
    "SessionArtifactRef",
    "SessionCompactor",
    "SessionLifecycleManager",
    "SessionRoleSpec",
    "SessionVisibility",
    "SharedSessionContextAssembler",
    "sanitize_session_content",
    "sanitize_session_content_with_report",
]
