import json
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from core.framework.llm import (
    LLMConfigurationError,
    LLMProviderError,
    LLMRequest,
    LLMRetryPolicy,
    OpenAICompatibleClient,
    OpenAICompatibleConfig,
)


def test_openai_compatible_client_requires_api_key_env(monkeypatch) -> None:
    monkeypatch.delenv("TEST_LLM_KEY", raising=False)
    client = OpenAICompatibleClient(
        OpenAICompatibleConfig(
            provider="test",
            base_url="https://llm.example/v1",
            model="test-model",
            api_key_env="TEST_LLM_KEY",
        ),
        transport=lambda request, timeout: b"{}",
    )

    with pytest.raises(LLMConfigurationError, match="TEST_LLM_KEY"):
        client.complete(LLMRequest(messages=[{"role": "user", "content": "hi"}]))


def test_openai_compatible_client_posts_chat_completion_and_normalizes_response(monkeypatch) -> None:
    monkeypatch.setenv("TEST_LLM_KEY", "redacted-test-key")
    captured: dict[str, object] = {}

    def transport(request: Request, timeout: float) -> bytes:
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["authorization"] = request.headers["Authorization"]
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return json.dumps(
            {
                "id": "chatcmpl-test",
                "choices": [{"message": {"content": "{\"ok\": true}"}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 5},
            }
        ).encode("utf-8")

    client = OpenAICompatibleClient(
        OpenAICompatibleConfig(
            provider="test",
            base_url="https://llm.example/v1/",
            model="test-model",
            api_key_env="TEST_LLM_KEY",
            timeout_seconds=12,
        ),
        transport=transport,
    )

    response = client.complete(
        LLMRequest(
            messages=[{"role": "user", "content": "hi"}],
            tools=[{"name": "memory.search"}],
        )
    )

    assert captured["url"] == "https://llm.example/v1/chat/completions"
    assert captured["timeout"] == 12
    assert captured["authorization"] == "Bearer redacted-test-key"
    assert captured["payload"] == {
        "model": "test-model",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "memory_search",
                    "description": "",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    }
    assert response.content == "{\"ok\": true}"
    assert response.usage.input_tokens == 7
    assert response.usage.output_tokens == 5
    assert response.usage.total_tokens == 12
    assert response.metadata == {
        "provider": "test",
        "model": "test-model",
        "response_id": "chatcmpl-test",
        "attempts": 1,
        "retry_count": 0,
    }


def test_dashscope_defaults_use_public_provider_values(monkeypatch) -> None:
    monkeypatch.delenv("DASHSCOPE_BASE_URL", raising=False)
    monkeypatch.delenv("NEWS_LLM_MODEL", raising=False)

    config = OpenAICompatibleConfig.dashscope_defaults()

    assert config.provider == "dashscope"
    assert config.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert config.model == "deepseek-v4-flash"
    assert config.api_key_env == "DASHSCOPE_API_KEY"


def test_openai_compatible_client_retries_rate_limit_then_succeeds(monkeypatch) -> None:
    monkeypatch.setenv("TEST_LLM_KEY", "redacted-test-key")
    calls: list[str] = []
    sleeps: list[float] = []

    def transport(request: Request, timeout: float) -> bytes:
        calls.append(request.full_url)
        if len(calls) == 1:
            raise HTTPError(request.full_url, 429, "rate limited", hdrs=None, fp=BytesIO(b""))
        return _success_body(response_id="retry-ok")

    client = OpenAICompatibleClient(
        OpenAICompatibleConfig(
            provider="test",
            base_url="https://llm.example/v1",
            model="test-model",
            api_key_env="TEST_LLM_KEY",
        ),
        transport=transport,
        retry_policy=LLMRetryPolicy(max_attempts=2, retry_delay_seconds=(0.25,)),
        sleep=sleeps.append,
    )

    response = client.complete(LLMRequest(messages=[{"role": "user", "content": "hi"}]))

    assert len(calls) == 2
    assert sleeps == [0.25]
    assert response.content == "{\"ok\": true}"
    assert response.metadata["attempts"] == 2
    assert response.metadata["retry_count"] == 1


def test_openai_compatible_client_does_not_retry_http_400(monkeypatch) -> None:
    monkeypatch.setenv("TEST_LLM_KEY", "redacted-test-key")
    calls = 0

    def transport(request: Request, timeout: float) -> bytes:
        nonlocal calls
        calls += 1
        raise HTTPError(request.full_url, 400, "bad request", hdrs=None, fp=BytesIO(b""))

    client = OpenAICompatibleClient(
        OpenAICompatibleConfig(
            provider="test",
            base_url="https://llm.example/v1",
            model="test-model",
            api_key_env="TEST_LLM_KEY",
        ),
        transport=transport,
        retry_policy=LLMRetryPolicy(max_attempts=3, retry_delay_seconds=(0,)),
        sleep=lambda seconds: None,
    )

    with pytest.raises(LLMProviderError) as exc_info:
        client.complete(LLMRequest(messages=[{"role": "user", "content": "hi"}]))

    assert calls == 1
    assert exc_info.value.retryable is False
    assert exc_info.value.status_code == 400
    assert exc_info.value.error_type == "invalid_request_schema"
    assert exc_info.value.attempts == 1


@pytest.mark.parametrize(
    ("status_code", "expected_error_type", "expected_retryable"),
    [
        (401, "invalid_api_key", False),
        (403, "invalid_api_key", False),
        (404, "invalid_model", False),
        (408, "provider_timeout", True),
        (413, "context_length_exceeded", False),
        (429, "rate_limited", True),
        (500, "provider_server_error", True),
        (502, "provider_server_error", True),
        (504, "provider_server_error", True),
    ],
)
def test_openai_compatible_client_classifies_http_provider_errors(
    monkeypatch,
    status_code: int,
    expected_error_type: str,
    expected_retryable: bool,
) -> None:
    monkeypatch.setenv("TEST_LLM_KEY", "redacted-test-key")
    calls = 0

    def transport(request: Request, timeout: float) -> bytes:
        nonlocal calls
        calls += 1
        raise HTTPError(request.full_url, status_code, "provider error", hdrs=None, fp=BytesIO(b""))

    client = OpenAICompatibleClient(
        OpenAICompatibleConfig(
            provider="test",
            base_url="https://llm.example/v1",
            model="test-model",
            api_key_env="TEST_LLM_KEY",
        ),
        transport=transport,
        retry_policy=LLMRetryPolicy(max_attempts=1, retry_delay_seconds=(0,)),
        sleep=lambda seconds: None,
    )

    with pytest.raises(LLMProviderError) as exc_info:
        client.complete(LLMRequest(messages=[{"role": "user", "content": "hi"}]))

    assert calls == 1
    assert exc_info.value.status_code == status_code
    assert exc_info.value.error_type == expected_error_type
    assert exc_info.value.retryable is expected_retryable


def test_openai_compatible_client_raises_after_exhausting_retryable_http_error(monkeypatch) -> None:
    monkeypatch.setenv("TEST_LLM_KEY", "redacted-test-key")
    calls = 0

    def transport(request: Request, timeout: float) -> bytes:
        nonlocal calls
        calls += 1
        raise HTTPError(request.full_url, 503, "unavailable", hdrs=None, fp=BytesIO(b""))

    client = OpenAICompatibleClient(
        OpenAICompatibleConfig(
            provider="test",
            base_url="https://llm.example/v1",
            model="test-model",
            api_key_env="TEST_LLM_KEY",
        ),
        transport=transport,
        retry_policy=LLMRetryPolicy(max_attempts=2, retry_delay_seconds=(0,)),
        sleep=lambda seconds: None,
    )

    with pytest.raises(LLMProviderError) as exc_info:
        client.complete(LLMRequest(messages=[{"role": "user", "content": "hi"}]))

    assert calls == 2
    assert exc_info.value.retryable is True
    assert exc_info.value.status_code == 503
    assert exc_info.value.error_type == "provider_server_error"
    assert exc_info.value.attempts == 2


def test_openai_compatible_client_does_not_retry_missing_api_key(monkeypatch) -> None:
    monkeypatch.delenv("TEST_LLM_KEY", raising=False)
    calls = 0

    def transport(request: Request, timeout: float) -> bytes:
        nonlocal calls
        calls += 1
        return _success_body()

    client = OpenAICompatibleClient(
        OpenAICompatibleConfig(
            provider="test",
            base_url="https://llm.example/v1",
            model="test-model",
            api_key_env="TEST_LLM_KEY",
        ),
        transport=transport,
        retry_policy=LLMRetryPolicy(max_attempts=3, retry_delay_seconds=(0,)),
        sleep=lambda seconds: None,
    )

    with pytest.raises(LLMConfigurationError):
        client.complete(LLMRequest(messages=[{"role": "user", "content": "hi"}]))

    assert calls == 0


def test_openai_compatible_client_does_not_retry_malformed_provider_response(monkeypatch) -> None:
    monkeypatch.setenv("TEST_LLM_KEY", "redacted-test-key")
    calls = 0

    def transport(request: Request, timeout: float) -> bytes:
        nonlocal calls
        calls += 1
        return json.dumps({"id": "bad-shape"}).encode("utf-8")

    client = OpenAICompatibleClient(
        OpenAICompatibleConfig(
            provider="test",
            base_url="https://llm.example/v1",
            model="test-model",
            api_key_env="TEST_LLM_KEY",
        ),
        transport=transport,
        retry_policy=LLMRetryPolicy(max_attempts=3, retry_delay_seconds=(0,)),
        sleep=lambda seconds: None,
    )

    with pytest.raises(LLMProviderError) as exc_info:
        client.complete(LLMRequest(messages=[{"role": "user", "content": "hi"}]))

    assert calls == 1
    assert exc_info.value.retryable is False
    assert exc_info.value.error_type == "provider_response_shape_invalid"
    assert exc_info.value.attempts == 1


def test_openai_compatible_client_retries_network_timeout_then_succeeds(monkeypatch) -> None:
    monkeypatch.setenv("TEST_LLM_KEY", "redacted-test-key")
    calls = 0

    def transport(request: Request, timeout: float) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise URLError(TimeoutError("timed out"))
        return _success_body()

    client = OpenAICompatibleClient(
        OpenAICompatibleConfig(
            provider="test",
            base_url="https://llm.example/v1",
            model="test-model",
            api_key_env="TEST_LLM_KEY",
        ),
        transport=transport,
        retry_policy=LLMRetryPolicy(max_attempts=2, retry_delay_seconds=(0,)),
        sleep=lambda seconds: None,
    )

    response = client.complete(LLMRequest(messages=[{"role": "user", "content": "hi"}]))

    assert calls == 2
    assert response.metadata["attempts"] == 2


def test_openai_compatible_client_sends_json_object_format_and_parses_structured_output(monkeypatch) -> None:
    monkeypatch.setenv("TEST_LLM_KEY", "redacted-test-key")
    captured: dict[str, object] = {}

    def transport(request: Request, timeout: float) -> bytes:
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _success_body(content="{\"title\":\"Report\",\"sections\":[]}")

    client = OpenAICompatibleClient(
        OpenAICompatibleConfig(
            provider="test",
            base_url="https://llm.example/v1",
            model="test-model",
            api_key_env="TEST_LLM_KEY",
        ),
        transport=transport,
    )

    response = client.complete(
        LLMRequest(
            messages=[{"role": "user", "content": "hi"}],
            response_format="json_object",
        )
    )

    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert response.content == "{\"title\":\"Report\",\"sections\":[]}"
    assert response.structured_output == {"title": "Report", "sections": []}


def test_openai_compatible_client_sends_json_schema_response_format(monkeypatch) -> None:
    monkeypatch.setenv("TEST_LLM_KEY", "redacted-test-key")
    captured: dict[str, object] = {}
    schema = {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
    }

    def transport(request: Request, timeout: float) -> bytes:
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _success_body(content="{\"title\":\"Report\"}")

    client = OpenAICompatibleClient(
        OpenAICompatibleConfig(
            provider="test",
            base_url="https://llm.example/v1",
            model="test-model",
            api_key_env="TEST_LLM_KEY",
        ),
        transport=transport,
    )

    response = client.complete(
        LLMRequest(
            messages=[{"role": "user", "content": "hi"}],
            output_schema=schema,
            output_schema_name="report",
        )
    )

    assert captured["payload"]["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "report",
            "strict": True,
            "schema": schema,
        },
    }
    assert response.structured_output == {"title": "Report"}


def test_openai_compatible_client_validates_structured_output_schema(monkeypatch) -> None:
    monkeypatch.setenv("TEST_LLM_KEY", "redacted-test-key")
    calls = 0
    schema = {
        "type": "object",
        "required": ["title"],
        "properties": {"title": {"type": "string"}},
        "additionalProperties": False,
    }

    def transport(request: Request, timeout: float) -> bytes:
        nonlocal calls
        calls += 1
        return _success_body(content="{\"sections\":[]}")

    client = OpenAICompatibleClient(
        OpenAICompatibleConfig(
            provider="test",
            base_url="https://llm.example/v1",
            model="test-model",
            api_key_env="TEST_LLM_KEY",
        ),
        transport=transport,
        retry_policy=LLMRetryPolicy(max_attempts=3, retry_delay_seconds=(0,)),
        sleep=lambda seconds: None,
    )

    with pytest.raises(LLMProviderError) as exc_info:
        client.complete(
            LLMRequest(
                messages=[{"role": "user", "content": "hi"}],
                output_schema=schema,
                output_schema_name="report",
            )
        )

    assert calls == 1
    assert exc_info.value.retryable is False
    assert exc_info.value.error_type == "structured_output_validation_error"
    assert "missing required property: title" in str(exc_info.value)


def test_openai_compatible_client_does_not_retry_invalid_structured_output(monkeypatch) -> None:
    monkeypatch.setenv("TEST_LLM_KEY", "redacted-test-key")
    calls = 0

    def transport(request: Request, timeout: float) -> bytes:
        nonlocal calls
        calls += 1
        return _success_body(content="not json")

    client = OpenAICompatibleClient(
        OpenAICompatibleConfig(
            provider="test",
            base_url="https://llm.example/v1",
            model="test-model",
            api_key_env="TEST_LLM_KEY",
        ),
        transport=transport,
        retry_policy=LLMRetryPolicy(max_attempts=3, retry_delay_seconds=(0,)),
        sleep=lambda seconds: None,
    )

    with pytest.raises(LLMProviderError) as exc_info:
        client.complete(
            LLMRequest(
                messages=[{"role": "user", "content": "hi"}],
                response_format="json_object",
            )
        )

    assert calls == 1
    assert exc_info.value.retryable is False
    assert exc_info.value.error_type == "structured_output_parse_error"


def test_openai_compatible_client_parses_provider_tool_calls(monkeypatch) -> None:
    monkeypatch.setenv("TEST_LLM_KEY", "redacted-test-key")

    def transport(request: Request, timeout: float) -> bytes:
        return json.dumps(
            {
                "id": "tool-call-ok",
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "memory_search",
                                        "arguments": "{\"query\":\"chips\"}",
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 7, "completion_tokens": 5},
            }
        ).encode("utf-8")

    client = OpenAICompatibleClient(
        OpenAICompatibleConfig(
            provider="test",
            base_url="https://llm.example/v1",
            model="test-model",
            api_key_env="TEST_LLM_KEY",
        ),
        transport=transport,
    )

    response = client.complete(
        LLMRequest(
            messages=[{"role": "user", "content": "hi"}],
            tools=[
                {
                    "name": "memory.search",
                    "description": "Search memory",
                    "input_schema": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                    },
                }
            ],
        )
    )

    assert response.content == ""
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].tool_name == "memory.search"
    assert response.tool_calls[0].arguments == {"query": "chips"}
    assert response.tool_calls[0].provider_tool_call_id == "call_1"


def test_openai_compatible_client_rejects_invalid_provider_tool_call_arguments(monkeypatch) -> None:
    monkeypatch.setenv("TEST_LLM_KEY", "redacted-test-key")

    def transport(request: Request, timeout: float) -> bytes:
        return json.dumps(
            {
                "id": "tool-call-bad",
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "memory_search",
                                        "arguments": "not json",
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {},
            }
        ).encode("utf-8")

    client = OpenAICompatibleClient(
        OpenAICompatibleConfig(
            provider="test",
            base_url="https://llm.example/v1",
            model="test-model",
            api_key_env="TEST_LLM_KEY",
        ),
        transport=transport,
    )

    with pytest.raises(LLMProviderError) as exc_info:
        client.complete(
            LLMRequest(
                messages=[{"role": "user", "content": "hi"}],
                tools=[{"name": "memory.search"}],
            )
        )

    assert exc_info.value.retryable is False
    assert exc_info.value.error_type == "tool_call_parse_error"


def test_openai_compatible_client_rejects_colliding_provider_tool_names(monkeypatch) -> None:
    monkeypatch.setenv("TEST_LLM_KEY", "redacted-test-key")
    calls = 0

    def transport(request: Request, timeout: float) -> bytes:
        nonlocal calls
        calls += 1
        return _success_body()

    client = OpenAICompatibleClient(
        OpenAICompatibleConfig(
            provider="test",
            base_url="https://llm.example/v1",
            model="test-model",
            api_key_env="TEST_LLM_KEY",
        ),
        transport=transport,
    )

    with pytest.raises(LLMProviderError) as exc_info:
        client.complete(
            LLMRequest(
                messages=[{"role": "user", "content": "hi"}],
                tools=[{"name": "memory.search"}, {"name": "memory_search"}],
            )
        )

    assert calls == 0
    assert exc_info.value.error_type == "invalid_request_schema"


def test_openai_compatible_client_streams_text_deltas_and_usage(monkeypatch) -> None:
    monkeypatch.setenv("TEST_LLM_KEY", "redacted-test-key")
    captured: dict[str, object] = {}

    def stream_transport(request: Request, timeout: float):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return [
            _sse({"id": "chatcmpl-stream", "choices": [{"delta": {"role": "assistant"}}]}),
            _sse({"id": "chatcmpl-stream", "choices": [{"delta": {"content": "hel"}}]}),
            _sse({"id": "chatcmpl-stream", "choices": [{"delta": {"content": "lo"}}]}),
            _sse({"id": "chatcmpl-stream", "choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 2}}),
            _sse({"id": "chatcmpl-stream", "choices": [{"delta": {}, "finish_reason": "stop"}]}),
            b"data: [DONE]\n\n",
        ]

    client = OpenAICompatibleClient(
        OpenAICompatibleConfig(
            provider="test",
            base_url="https://llm.example/v1",
            model="test-model",
            api_key_env="TEST_LLM_KEY",
        ),
        stream_transport=stream_transport,
    )

    events = list(client.stream(LLMRequest(messages=[{"role": "user", "content": "hi"}])))

    assert captured["url"] == "https://llm.example/v1/chat/completions"
    assert captured["payload"]["stream"] is True
    assert [event.event_type for event in events] == [
        "message_start",
        "text_delta",
        "text_delta",
        "usage_delta",
        "message_complete",
    ]
    assert events[1].text_delta == "hel"
    assert events[2].text_delta == "lo"
    assert events[3].usage_delta.input_tokens == 3
    assert events[3].usage_delta.output_tokens == 2
    assert events[-1].metadata == {
        "provider": "test",
        "model": "test-model",
        "response_id": "chatcmpl-stream",
        "finish_reason": "stop",
        "attempts": 1,
        "retry_count": 0,
    }


def test_openai_compatible_client_streams_fragmented_tool_call(monkeypatch) -> None:
    monkeypatch.setenv("TEST_LLM_KEY", "redacted-test-key")

    def stream_transport(request: Request, timeout: float):
        return [
            _sse(
                {
                    "id": "chatcmpl-tools",
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "memory_search",
                                            "arguments": "{\"query\"",
                                        },
                                    }
                                ]
                            }
                        }
                    ],
                }
            ),
            _sse(
                {
                    "id": "chatcmpl-tools",
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "function": {"arguments": ": \"chips\"}"},
                                    }
                                ]
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                }
            ),
            b"data: [DONE]\n\n",
        ]

    client = OpenAICompatibleClient(
        OpenAICompatibleConfig(
            provider="test",
            base_url="https://llm.example/v1",
            model="test-model",
            api_key_env="TEST_LLM_KEY",
        ),
        stream_transport=stream_transport,
    )

    events = list(
        client.stream(
            LLMRequest(
                messages=[{"role": "user", "content": "hi"}],
                tools=[{"name": "memory.search"}],
            )
        )
    )

    tool_event = events[1]

    assert [event.event_type for event in events] == [
        "message_start",
        "tool_call_complete",
        "message_complete",
    ]
    assert tool_event.tool_call.tool_name == "memory.search"
    assert tool_event.tool_call.arguments == {"query": "chips"}
    assert tool_event.tool_call.provider_tool_call_id == "call_1"
    assert events[-1].metadata["finish_reason"] == "tool_calls"


def test_openai_compatible_client_stream_rejects_invalid_chunk(monkeypatch) -> None:
    monkeypatch.setenv("TEST_LLM_KEY", "redacted-test-key")

    def stream_transport(request: Request, timeout: float):
        return [b"data: not-json\n\n"]

    client = OpenAICompatibleClient(
        OpenAICompatibleConfig(
            provider="test",
            base_url="https://llm.example/v1",
            model="test-model",
            api_key_env="TEST_LLM_KEY",
        ),
        stream_transport=stream_transport,
    )

    with pytest.raises(LLMProviderError) as exc_info:
        list(client.stream(LLMRequest(messages=[{"role": "user", "content": "hi"}])))

    assert exc_info.value.retryable is False
    assert exc_info.value.error_type == "provider_stream_chunk_invalid"


def _success_body(*, response_id: str = "chatcmpl-test", content: str = "{\"ok\": true}") -> bytes:
    return json.dumps(
        {
            "id": response_id,
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 5},
        }
    ).encode("utf-8")


def _sse(payload: dict) -> bytes:
    return f"data: {json.dumps(payload)}\n\n".encode("utf-8")
