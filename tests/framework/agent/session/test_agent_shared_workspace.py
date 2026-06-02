from __future__ import annotations

from datetime import datetime

import pytest

from framework.agent.session import AgentSharedWorkspace, InMemoryAgentSessionStore


def test_workspace_write_populates_created_at() -> None:
    workspace = AgentSharedWorkspace(InMemoryAgentSessionStore())

    item = workspace.write(
        session_id="session-1",
        agent_id="agent-a",
        role="observation",
        content={"result": "ok"},
    )

    assert item.created_at is not None
    assert datetime.fromisoformat(item.created_at)


def test_workspace_sanitizes_sensitive_fields_without_mutating_input() -> None:
    workspace = AgentSharedWorkspace(InMemoryAgentSessionStore())
    content = {
        "safe": "visible",
        "full_text": "raw paper text",
        "fullText": "raw paper text",
        "nested": {"api_key": "secret", "apiKey": "secret", "value": "kept"},
        "items": [{"token": "secret-token", "name": "kept"}],
    }

    item = workspace.write(
        session_id="session-1",
        agent_id="agent-a",
        role="observation",
        content=content,
        refs={"raw_payload": {"secret": True}, "run_id": "run-1"},
        metadata={"authorization": "Bearer secret", "source": "test"},
    )

    assert "full_text" not in item.content
    assert "fullText" not in item.content
    assert item.content["nested"] == {"value": "kept"}
    assert item.content["items"] == [{"name": "kept"}]
    assert content["full_text"] == "raw paper text"
    assert item.refs == {"run_id": "run-1"}
    assert item.metadata["source"] == "test"
    assert set(item.metadata["redacted_fields"]) >= {
        "full_text",
        "fullText",
        "nested.api_key",
        "nested.apiKey",
        "items[0].token",
        "refs.raw_payload",
        "metadata.authorization",
    }


def test_workspace_rejects_empty_required_ids() -> None:
    workspace = AgentSharedWorkspace(InMemoryAgentSessionStore())

    with pytest.raises(ValueError):
        workspace.write(session_id="", agent_id="agent-a", role="observation", content={})


def test_workspace_rejects_non_mapping_content() -> None:
    workspace = AgentSharedWorkspace(InMemoryAgentSessionStore())

    with pytest.raises(TypeError):
        workspace.write(
            session_id="session-1",
            agent_id="agent-a",
            role="observation",
            content=["not", "mapping"],  # type: ignore[arg-type]
        )
