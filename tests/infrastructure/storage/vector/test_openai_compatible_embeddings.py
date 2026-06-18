import json
from io import BytesIO
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from infrastructure.storage.vector import (
    DeterministicEmbeddingModel,
    EmbeddingConfigurationError,
    EmbeddingProviderError,
    OpenAICompatibleEmbeddingConfig,
    OpenAICompatibleEmbeddingModel,
    embedding_model_from_env,
)


def test_embedding_model_from_env_uses_deterministic_fallback_without_provider_config() -> None:
    model = embedding_model_from_env(env={}, vector_size=8)

    assert isinstance(model, DeterministicEmbeddingModel)
    assert model.dimension == 8


def test_embedding_dimensions_alone_does_not_enable_provider_embedding() -> None:
    model = embedding_model_from_env(env={"NEWS_EMBEDDING_DIMENSIONS": "8"}, vector_size=8)

    assert isinstance(model, DeterministicEmbeddingModel)


def test_dashscope_embedding_defaults_use_openai_compatible_public_values() -> None:
    config = OpenAICompatibleEmbeddingConfig.from_env(
        env={"NEWS_EMBEDDING_PROVIDER": "dashscope"},
        vector_size=64,
    )

    assert config.provider == "dashscope"
    assert config.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert config.model == "text-embedding-v4"
    assert config.api_key_env == "DASHSCOPE_API_KEY"
    assert config.request_dimensions == 64
    assert config.batch_size == 10


def test_openai_compatible_embedding_posts_embeddings_and_normalizes_response_order() -> None:
    captured: dict[str, object] = {}

    def transport(request: Request, timeout: float) -> bytes:
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["authorization"] = request.headers["Authorization"]
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return json.dumps(
            {
                "object": "list",
                "data": [
                    {"object": "embedding", "index": 1, "embedding": [0.4, 0.5, 0.6]},
                    {"object": "embedding", "index": 0, "embedding": [0.1, 0.2, 0.3]},
                ],
            }
        ).encode("utf-8")

    model = OpenAICompatibleEmbeddingModel(
        OpenAICompatibleEmbeddingConfig(
            provider="test",
            base_url="https://embedding.example/v1/",
            model="embedding-model",
            api_key_env="TEST_EMBEDDING_KEY",
            vector_size=3,
            request_dimensions=3,
            timeout_seconds=12,
        ),
        env={"TEST_EMBEDDING_KEY": "redacted-test-key"},
        transport=transport,
    )

    vectors = model.embed_texts(["alpha", "beta"])

    assert captured["url"] == "https://embedding.example/v1/embeddings"
    assert captured["timeout"] == 12
    assert captured["authorization"] == "Bearer redacted-test-key"
    assert captured["payload"] == {
        "model": "embedding-model",
        "input": ["alpha", "beta"],
        "dimensions": 3,
    }
    assert vectors == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]


def test_openai_compatible_embedding_batches_provider_requests() -> None:
    payloads = []

    def transport(request: Request, timeout: float) -> bytes:
        payload = json.loads(request.data.decode("utf-8"))
        payloads.append(payload)
        return json.dumps(
            {
                "data": [
                    {"index": index, "embedding": [float(index), 0.0]}
                    for index, _ in enumerate(payload["input"])
                ]
            }
        ).encode("utf-8")

    model = OpenAICompatibleEmbeddingModel(
        OpenAICompatibleEmbeddingConfig(
            provider="test",
            base_url="https://embedding.example/v1",
            model="embedding-model",
            api_key_env="TEST_EMBEDDING_KEY",
            vector_size=2,
            batch_size=2,
        ),
        env={"TEST_EMBEDDING_KEY": "redacted-test-key"},
        transport=transport,
    )

    vectors = model.embed_texts(["a", "b", "c"])

    assert [payload["input"] for payload in payloads] == [["a", "b"], ["c"]]
    assert vectors == [[0.0, 0.0], [1.0, 0.0], [0.0, 0.0]]


def test_openai_compatible_embedding_requires_api_key_env_before_request() -> None:
    calls = 0

    def transport(request: Request, timeout: float) -> bytes:
        nonlocal calls
        calls += 1
        return b"{}"

    model = OpenAICompatibleEmbeddingModel(
        OpenAICompatibleEmbeddingConfig(
            provider="test",
            base_url="https://embedding.example/v1",
            model="embedding-model",
            api_key_env="TEST_EMBEDDING_KEY",
            vector_size=2,
        ),
        env={},
        transport=transport,
    )

    with pytest.raises(EmbeddingConfigurationError, match="TEST_EMBEDDING_KEY"):
        model.embed_text("alpha")

    assert calls == 0


def test_openai_compatible_embedding_rejects_dimension_mismatch() -> None:
    model = OpenAICompatibleEmbeddingModel(
        OpenAICompatibleEmbeddingConfig(
            provider="test",
            base_url="https://embedding.example/v1",
            model="embedding-model",
            api_key_env="TEST_EMBEDDING_KEY",
            vector_size=3,
        ),
        env={"TEST_EMBEDDING_KEY": "redacted-test-key"},
        transport=lambda request, timeout: json.dumps(
            {"data": [{"index": 0, "embedding": [0.1, 0.2]}]}
        ).encode("utf-8"),
    )

    with pytest.raises(EmbeddingProviderError) as exc_info:
        model.embed_text("alpha")

    assert exc_info.value.error_type == "embedding_dimension_mismatch"


def test_openai_compatible_embedding_maps_http_error() -> None:
    def transport(request: Request, timeout: float) -> bytes:
        raise HTTPError(request.full_url, 429, "rate limited", hdrs=None, fp=BytesIO(b""))

    model = OpenAICompatibleEmbeddingModel(
        OpenAICompatibleEmbeddingConfig(
            provider="test",
            base_url="https://embedding.example/v1",
            model="embedding-model",
            api_key_env="TEST_EMBEDDING_KEY",
            vector_size=2,
        ),
        env={"TEST_EMBEDDING_KEY": "redacted-test-key"},
        transport=transport,
    )

    with pytest.raises(EmbeddingProviderError) as exc_info:
        model.embed_text("alpha")

    assert exc_info.value.status_code == 429
    assert exc_info.value.error_type == "rate_limited"


def test_generic_openai_compatible_embedding_requires_base_url_and_model() -> None:
    with pytest.raises(EmbeddingConfigurationError, match="NEWS_EMBEDDING_BASE_URL"):
        OpenAICompatibleEmbeddingConfig.from_env(
            env={"NEWS_EMBEDDING_PROVIDER": "openai-compatible"},
            vector_size=64,
        )

    with pytest.raises(EmbeddingConfigurationError, match="NEWS_EMBEDDING_MODEL"):
        OpenAICompatibleEmbeddingConfig.from_env(
            env={
                "NEWS_EMBEDDING_PROVIDER": "openai-compatible",
                "NEWS_EMBEDDING_BASE_URL": "https://embedding.example/v1",
            },
            vector_size=64,
        )
