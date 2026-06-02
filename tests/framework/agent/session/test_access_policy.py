from __future__ import annotations

import pytest

from framework.agent.session import (
    AgentSessionItem,
    AgentSharedWorkspace,
    AgentSessionQuery,
    InMemoryAgentSessionStore,
    SessionAccessPolicy,
    SessionRoleSpec,
    SessionVisibility,
)
from framework.agent.session.exceptions import AgentSessionAccessDenied


def test_access_policy_restricts_writes_and_private_reads() -> None:
    policy = SessionAccessPolicy(
        (
            SessionRoleSpec(
                role="private-note",
                readable_by=("reviewer",),
                writable_by=("owner",),
                visibility=SessionVisibility.PRIVATE,
            ),
        )
    )
    workspace = AgentSharedWorkspace(InMemoryAgentSessionStore(), access_policy=policy)

    with pytest.raises(AgentSessionAccessDenied):
        workspace.write(
            session_id="session-1",
            run_id="run-1",
            agent_id="other",
            role="private-note",
            content={"value": "hidden"},
        )

    item = workspace.write(
        session_id="session-1",
        run_id="run-1",
        agent_id="owner",
        role="private-note",
        content={"value": "hidden"},
    )

    query = AgentSessionQuery(
        session_id="session-1",
        roles=("private-note",),
        visibility=tuple(SessionVisibility),
        include_private=True,
        statuses=(),
    )
    assert workspace.query(query) == ()
    assert workspace.query(query, reader_agent_id="owner") == (item,)
    assert workspace.query(query, reader_agent_id="paper-analysis-orchestrator") == (item,)
    assert workspace.query(query, reader_agent_id="reviewer") == ()
    assert workspace.read(session_id="session-1", roles=("private-note",), include_private=True) == ()
    assert workspace.latest(session_id="session-1", role="private-note") is None
    assert workspace.latest(session_id="session-1", role="private-note", include_private=True) is None
    assert workspace.latest(session_id="session-1", role="private-note", reader_agent_id="owner", include_private=True) == item


def test_default_policy_allows_shared_public_and_final_reads() -> None:
    policy = SessionAccessPolicy()
    for visibility in (SessionVisibility.PUBLIC, SessionVisibility.SHARED, SessionVisibility.FINAL):
        item = AgentSessionItem(
            session_id="session-1",
            run_id="run-1",
            agent_id="writer",
            role="role",
            content={"ok": True},
            visibility=visibility,
        )
        assert policy.can_read(agent_id="reader", item=item) is True
