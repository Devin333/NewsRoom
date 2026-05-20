import pytest

from framework.llm import (
    LLMStreamAccumulator,
    LLMStreamEvent,
    LLMToolCall,
    REDACTED_VALUE,
    TokenUsage,
)


def test_stream_accumulator_collects_text_usage_and_completion_metadata() -> None:
    accumulator = LLMStreamAccumulator(metadata={"provider": "test", "model": "demo", "response_format": "json_object", "tool_count": 1})

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
    assert response.metadata == {"provider": "test", "model": "demo", "response_format": "json_object", "tool_count": 1, "finish_reason": "stop"}


def test_stream_accumulator_collects_completed_tool_calls() -> None:
    accumulator = LLMStreamAccumulator()
    tool_call = LLMToolCall(
        tool_call_id="call_1",
        tool_name="memory.search",
        arguments={"query": "chips"},
    )

    accumulator.add_event(LLMStreamEvent(event_type="message_start"))
    accumulator.add_event(LLMStreamEvent(event_type="tool_call_complete", tool_call=tool_call))
    accumulator.add_event(LLMStreamEvent(event_type="message_complete"))

    response = accumulator.to_response()

    assert response.tool_calls == [tool_call]


def test_stream_accumulator_rebuilds_tool_call_from_deltas() -> None:
    accumulator = LLMStreamAccumulator()

    accumulator.add_event(LLMStreamEvent(event_type="message_start"))
    accumulator.add_event(
        LLMStreamEvent(
            event_type="tool_call_start",
            tool_call_delta={
                "tool_call_id": "call_1",
                "provider_tool_call_id": "provider_call_1",
                "tool_name": "memory.search",
                "arguments": "{\"query\"",
            },
        )
    )
    accumulator.add_event(
        LLMStreamEvent(
            event_type="tool_call_delta",
            tool_call_delta={"tool_call_id": "call_1", "arguments": ": \"chips\"}"},
        )
    )
    accumulator.add_event(LLMStreamEvent(event_type="message_complete"))

    response = accumulator.to_response()

    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].tool_name == "memory.search"
    assert response.tool_calls[0].arguments == {"query": "chips"}
    assert response.tool_calls[0].provider_tool_call_id == "provider_call_1"


def test_stream_accumulator_rejects_out_of_order_events() -> None:
    accumulator = LLMStreamAccumulator()

    with pytest.raises(ValueError, match="before message_start"):
        accumulator.add_event(LLMStreamEvent(event_type="text_delta", text_delta="oops"))


def test_stream_accumulator_error_event_interrupts_response() -> None:
    accumulator = LLMStreamAccumulator()

    accumulator.add_event(LLMStreamEvent(event_type="message_start"))

    with pytest.raises(RuntimeError, match="rate_limit"):
        accumulator.add_event(
            LLMStreamEvent(event_type="error", metadata={"error_type": "rate_limit"})
        )

    with pytest.raises(ValueError, match="after error"):
        accumulator.add_event(LLMStreamEvent(event_type="text_delta", text_delta="late"))


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

