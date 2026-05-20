from __future__ import annotations

from framework.llm import (
    LLMMessage,
    LLMMessageRole,
    LLMRequest,
    LLMResponse,
    LLMToolCall,
    TokenUsage,
)


def test_message_helpers_round_trip() -> None:
    message = LLMMessage.tool("done", "call_1")

    payload = message.to_dict()

    assert payload == {"role": "tool", "content": "done", "tool_call_id": "call_1"}
    assert LLMMessage.from_dict(payload) == message
    assert LLMMessage.system("s").role == LLMMessageRole.SYSTEM.value


def test_request_accepts_prd_and_legacy_messages() -> None:
    request = LLMRequest(
        messages=[LLMMessage.user("hello"), {"role": "assistant", "content": "hi"}],
        model="demo",
        temperature=0.2,
        max_tokens=128,
    )

    payload = request.to_dict(redact=False)
    restored = LLMRequest.from_dict(payload)

    assert payload["messages"][0] == {"role": "user", "content": "hello"}
    assert restored.model == "demo"
    assert restored.estimated_prompt_text() == "hello\nhi"


def test_response_tool_call_usage_round_trip() -> None:
    tool_call = LLMToolCall(
        tool_call_id="call_1",
        tool_name="memory.recall",
        raw_arguments='{"query": "agent"}',
    )
    response = LLMResponse(
        content=None,
        usage=TokenUsage(input_tokens=2, output_tokens=3),
        tool_calls=[tool_call],
        model="demo",
        raw={"id": "resp_1"},
    )

    restored = LLMResponse.from_dict(response.to_dict(redact=False))

    assert response.usage.total_tokens == 5
    assert response.usage.total_tokens() == 5
    assert response.has_tool_calls() is True
    assert response.tool_calls[0].arguments_dict() == {"query": "agent"}
    assert restored.model == "demo"
    assert restored.raw == {"id": "resp_1"}
