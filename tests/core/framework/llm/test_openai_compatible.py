import json
from urllib.request import Request

import pytest

from core.framework.llm import (
    LLMConfigurationError,
    LLMRequest,
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
    }


def test_dashscope_defaults_use_public_provider_values(monkeypatch) -> None:
    monkeypatch.delenv("DASHSCOPE_BASE_URL", raising=False)
    monkeypatch.delenv("NEWS_LLM_MODEL", raising=False)

    config = OpenAICompatibleConfig.dashscope_defaults()

    assert config.provider == "dashscope"
    assert config.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert config.model == "deepseek-v4-flash"
    assert config.api_key_env == "DASHSCOPE_API_KEY"
