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
        "tools": [{"name": "memory.search"}],
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


def _success_body(*, response_id: str = "chatcmpl-test") -> bytes:
    return json.dumps(
        {
            "id": response_id,
            "choices": [{"message": {"content": "{\"ok\": true}"}}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 5},
        }
    ).encode("utf-8")
