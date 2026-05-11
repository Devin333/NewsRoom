import pytest

from core.framework.llm import (
    LLMStreamAccumulator,
    LLMStreamEvent,
    LLMToolCall,
    REDACTED_VALUE,
    TokenUsage,
)


def test_stream_accumulator_collects_text_usage_and_completion_metadata() -> None:
    accumulator = LLMStreamAccumulator(metadata={"provider": "test"})

    accumulator.add_event(LLMStreamEvent(event_type="message_start"))
    accumulator.add_event(LLMStreamEvent(event_type="text_delta", text_delta="hello "))
    accumulator.add_event(LLMStreamEvent(event_type="text_delta", text_delta="world"))
    accumulator.add_event(
        LLMStreamEvent(event_type="usage_delta", usage_delta=TokenUsage(input_tokens=5, output_tokens=2))
    )
    accumulator.add_event(
        LLMStreamEvent(event_type="usage_delta", usage_delta=TokenUsage(input_tokens=1, output_tokens=3))
    )
    accumulator.add_event(LLMStreamEvent(event_type="message_complete", metadata={"finish_reason": "stop"}))

    response = accumulator.to_response()

    assert response.content == "hello world"
    assert response.usage.input_tokens == 6
    assert response.usage.output_tokens == 5
    assert response.usage.total_tokens == 11
    assert response.metadata == {"provider": "test", "finish_reason": "stop"}


def test_stream_accumulator_collects_completed_tool_calls() -> None:
    accumulator = LLMStreamAccumulator()
    tool_call = LLMToolCall(
        tool_call_id="call_1",
        tool_name="memory.search",
        arguments={"query": "chips"},
    )

    accumulator.add_event(LLMStreamEvent(event_type="tool_call_complete", tool_call=tool_call))

    response = accumulator.to_response()

    assert response.tool_calls == [tool_call]


def test_stream_event_to_dict_redacts_sensitive_values() -> None:
    secret = "sk" + "-stream-secret-value"
    event = LLMStreamEvent(
        event_type="text_delta",
        text_delta=f"token {secret}",
        metadata={"api_key": secret},
    )

    payload = event.to_dict()

    assert secret not in str(payload)
    assert payload["text_delta"] == f"token {REDACTED_VALUE}"
    assert payload["metadata"]["api_key"] == REDACTED_VALUE


def test_stream_event_rejects_unknown_event_type() -> None:
    with pytest.raises(ValueError, match="unsupported LLM stream event type"):
        LLMStreamEvent(event_type="unknown")
