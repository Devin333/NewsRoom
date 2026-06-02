from __future__ import annotations

from framework.agent.session import AgentSessionItem, SharedSessionContextAssembler


def test_assembler_outputs_readable_context() -> None:
    item = AgentSessionItem(
        session_id="session-1",
        agent_id="agent-a",
        role="decision",
        content={"answer": "yes", "token": "secret"},
        summary="Agent decided yes.",
        confidence=0.9,
    )

    context = SharedSessionContextAssembler().assemble(session_id="session-1", items=[item])

    assert '<shared_agent_session session_id="session-1">' in context.context_text
    assert '<item role="decision" agent_id="agent-a" confidence="0.9" status="active" visibility="shared">' in context.context_text
    assert "<summary>Agent decided yes.</summary>" in context.context_text
    assert "secret" not in context.context_text
    assert "token" not in context.context_text
    assert context.char_count == len(context.context_text)


def test_assembler_truncates_context() -> None:
    item = AgentSessionItem(
        session_id="session-1",
        agent_id="agent-a",
        role="observation",
        content={"text": "x" * 500},
    )

    context = SharedSessionContextAssembler().assemble(
        session_id="session-1",
        items=[item],
        max_context_chars=120,
    )

    assert len(context.context_text) <= 120
    assert context.char_count == len(context.context_text)
