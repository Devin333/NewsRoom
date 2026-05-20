from __future__ import annotations

from framework.llm import (
    CachedLLMClient,
    FakeLLMClient,
    InMemoryLLMCache,
    LLMCachePolicy,
    LLMRedactor,
    LLMRequest,
    LLMResponse,
    LLMStreamAccumulator,
    PromptRenderer,
    PromptTemplate,
    PromptVariables,
    REDACTED_VALUE,
)


def test_fake_client_supports_prd_helpers_and_streaming() -> None:
    client = FakeLLMClient(responses=None)
    client.push_response("hello")
    client.push_response("streamed")

    response = client.complete(LLMRequest(messages=[{"role": "user", "content": "go"}]))
    events = list(client.stream(LLMRequest(messages=[{"role": "user", "content": "stream"}])))

    assert response.content == "hello"
    assert client.calls()[0].messages[0]["content"] == "go"
    assert events[0].event_type == "message_start"
    assert events[-1].event_type == "message_complete"


def test_stream_accumulator_add_alias() -> None:
    client = FakeLLMClient(["hi"])
    accumulator = LLMStreamAccumulator()

    for event in client.stream(LLMRequest(messages=[{"role": "user", "content": "go"}])):
        accumulator.add(event)

    assert accumulator.to_response().content == "hi"


def test_cached_client_and_in_memory_cache() -> None:
    client = FakeLLMClient(["first"])
    cached = CachedLLMClient(
        client,
        provider="test",
        model="demo",
        policy=LLMCachePolicy(enabled=True, cacheable_task_types=("classify",)),
        cache=InMemoryLLMCache(),
    )
    request = LLMRequest(
        messages=[{"role": "user", "content": "private"}],
        metadata={"task_type": "classify"},
    )

    first = cached.complete(request)
    second = cached.complete(request)

    assert first.metadata["llm_cache_hit"] is False
    assert second.metadata["llm_cache_hit"] is True
    assert client.call_count == 1


def test_prompt_renderer_and_llm_redactor() -> None:
    rendered = PromptRenderer().render(
        PromptTemplate("Hello {name}"),
        PromptVariables({"name": "Ada"}),
    )
    redacted = LLMRedactor().redact_request(
        LLMRequest(messages=[{"role": "user", "content": "secret"}], metadata={"api_key": "sk-test"})
    )

    assert rendered == "Hello Ada"
    assert redacted.metadata["api_key"] == REDACTED_VALUE
