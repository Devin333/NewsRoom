from framework.agent.messages import (
    AgentMessage,
    AgentMessageFormatter,
    AgentMessageRole,
    MessageHistory,
    Scratchpad,
)
from framework.agent.models import AgentAction


def test_message_history_scratchpad_and_formatter() -> None:
    history = MessageHistory()
    history.append(AgentMessage(role=AgentMessageRole.USER, content="hello"))
    history.append(AgentMessage.from_dict({"role": "assistant", "content": "hi"}))

    scratchpad = Scratchpad()
    scratchpad.add_thought("inspect")
    scratchpad.add_observation("ok")

    formatter = AgentMessageFormatter()

    assert history.latest(1)[0].content == "hi"
    assert history.to_llm_messages()[0] == {"role": "user", "content": "hello"}
    assert "thought: inspect" in scratchpad.render()
    assert '"action_type": "tool_call"' in formatter.format_action(
        AgentAction.tool_call("memory.search", {"query": "ai"})
    )
