from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_DASHSCOPE_EMBEDDING_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_DASHSCOPE_EMBEDDING_MODEL = "text-embedding-v4"


class EmbeddingModel(Protocol):
    dimension: int

    def embed_text(self, text: str) -> list[float]: ...

    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


class EmbeddingConfigurationError(RuntimeError):
    """Raised when embedding provider configuration is incomplete."""


class EmbeddingProviderError(RuntimeError):
    """Raised when an embedding provider request fails or returns invalid data."""

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        error_type: str = "unknown_embedding_error",
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.error_type = error_type
        self.status_code = status_code


EmbeddingTransport = Callable[[Request, float], bytes]


class DeterministicEmbeddingModel:
    def __init__(self, *, dimension: int = 64) -> None:
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self.dimension = dimension

    def embed_text(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = _tokenize(text)
        if not tokens:
            return vector
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        return _normalize(vector)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(text) for text in texts]


class FakeEmbeddingAdapter(DeterministicEmbeddingModel):
    """Stable deterministic embedding adapter for storage tests."""


@dataclass(frozen=True)
class OpenAICompatibleEmbeddingConfig:
    provider: str
    base_url: str
    model: str
    api_key_env: str
    vector_size: int
    request_dimensions: int | None = None
    batch_size: int = 10
    timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("provider is required")
        if not self.base_url.strip():
            raise ValueError("base_url is required")
        if not self.model.strip():
            raise ValueError("model is required")
        if not self.api_key_env.strip():
            raise ValueError("api_key_env is required")
        if self.vector_size <= 0:
            raise ValueError("vector_size must be positive")
        if self.request_dimensions is not None and self.request_dimensions <= 0:
            raise ValueError("request_dimensions must be positive")
        if self.batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    @classmethod
    def from_env(
        cls,
        *,
        env: Mapping[str, str] | None = None,
        vector_size: int,
    ) -> "OpenAICompatibleEmbeddingConfig":
        values = env if env is not None else os.environ
        provider = _normalize_provider(values.get("NEWS_EMBEDDING_PROVIDER", "openai-compatible"))
        if provider == "dashscope":
            return cls(
                provider="dashscope",
                base_url=values.get("NEWS_EMBEDDING_BASE_URL")
                or values.get("DASHSCOPE_BASE_URL")
                or DEFAULT_DASHSCOPE_EMBEDDING_BASE_URL,
                model=values.get("NEWS_EMBEDDING_MODEL", DEFAULT_DASHSCOPE_EMBEDDING_MODEL),
                api_key_env=values.get("NEWS_EMBEDDING_API_KEY_ENV", "DASHSCOPE_API_KEY"),
                vector_size=vector_size,
                request_dimensions=_optional_int(values.get("NEWS_EMBEDDING_DIMENSIONS"), default=vector_size),
                batch_size=_optional_int_required(values.get("NEWS_EMBEDDING_BATCH_SIZE"), default=10),
                timeout_seconds=_optional_float(values.get("NEWS_EMBEDDING_TIMEOUT_SECONDS"), default=60.0),
            )

        base_url = values.get("NEWS_EMBEDDING_BASE_URL")
        if not base_url:
            raise EmbeddingConfigurationError("missing required environment variable: NEWS_EMBEDDING_BASE_URL")
        model = values.get("NEWS_EMBEDDING_MODEL")
        if not model:
            raise EmbeddingConfigurationError("missing required environment variable: NEWS_EMBEDDING_MODEL")
        return cls(
            provider=provider,
            base_url=base_url,
            model=model,
            api_key_env=values.get("NEWS_EMBEDDING_API_KEY_ENV", "NEWS_EMBEDDING_API_KEY"),
            vector_size=vector_size,
            request_dimensions=_optional_int(values.get("NEWS_EMBEDDING_DIMENSIONS"), default=None),
            batch_size=_optional_int_required(values.get("NEWS_EMBEDDING_BATCH_SIZE"), default=128),
            timeout_seconds=_optional_float(values.get("NEWS_EMBEDDING_TIMEOUT_SECONDS"), default=60.0),
        )


class OpenAICompatibleEmbeddingModel:
    def __init__(
        self,
        config: OpenAICompatibleEmbeddingConfig,
        *,
        env: Mapping[str, str] | None = None,
        transport: EmbeddingTransport | None = None,
    ) -> None:
        self.config = config
        self.dimension = config.vector_size
        self._env = env if env is not None else os.environ
        self._transport = transport or _urlopen_transport

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        api_key = self._resolve_api_key()
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.config.batch_size):
            batch = texts[start : start + self.config.batch_size]
            request = self._build_http_request(api_key, batch)
            try:
                raw_body = self._transport(request, self.config.timeout_seconds)
            except HTTPError as exc:
                raise EmbeddingProviderError(
                    f"{self.config.provider} embedding request failed: HTTP {int(exc.code)}",
                    provider=self.config.provider,
                    error_type=_error_type_from_http_status(int(exc.code)),
                    status_code=int(exc.code),
                ) from exc
            except (TimeoutError, URLError, OSError) as exc:
                raise EmbeddingProviderError(
                    f"{self.config.provider} embedding request failed: provider_connection_error",
                    provider=self.config.provider,
                    error_type="provider_connection_error",
                ) from exc
            payload = self._parse_response_payload(raw_body)
            vectors.extend(self._vectors_from_payload(payload, expected_count=len(batch)))
        return vectors

    def _resolve_api_key(self) -> str:
        api_key = self._env.get(self.config.api_key_env)
        if not api_key:
            raise EmbeddingConfigurationError(
                f"missing required environment variable: {self.config.api_key_env}"
            )
        return api_key

    def _build_http_request(self, api_key: str, texts: list[str]) -> Request:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "input": list(texts),
        }
        if self.config.request_dimensions is not None:
            payload["dimensions"] = self.config.request_dimensions
        return Request(
            url=f"{self.config.base_url.rstrip('/')}/embeddings",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

    def _parse_response_payload(self, raw_body: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EmbeddingProviderError(
                f"{self.config.provider} embedding response payload is not valid JSON",
                provider=self.config.provider,
                error_type="provider_response_shape_invalid",
            ) from exc
        if not isinstance(payload, dict):
            raise EmbeddingProviderError(
                f"{self.config.provider} embedding response payload is not an object",
                provider=self.config.provider,
                error_type="provider_response_shape_invalid",
            )
        return payload

    def _vectors_from_payload(self, payload: dict[str, Any], *, expected_count: int) -> list[list[float]]:
        items = payload.get("data")
        if not isinstance(items, list) or len(items) != expected_count:
            raise EmbeddingProviderError(
                f"{self.config.provider} embedding response data count is invalid",
                provider=self.config.provider,
                error_type="provider_response_shape_invalid",
            )

        ordered = sorted(enumerate(items), key=_embedding_item_sort_key)
        return [self._vector_from_item(item) for _, item in ordered]

    def _vector_from_item(self, item: Any) -> list[float]:
        if not isinstance(item, dict):
            raise EmbeddingProviderError(
                f"{self.config.provider} embedding response item is not an object",
                provider=self.config.provider,
                error_type="provider_response_shape_invalid",
            )
        embedding = item.get("embedding")
        if not isinstance(embedding, list):
            raise EmbeddingProviderError(
                f"{self.config.provider} embedding response missing embedding vector",
                provider=self.config.provider,
                error_type="provider_response_shape_invalid",
            )
        vector = [_coerce_float(value, provider=self.config.provider) for value in embedding]
        if len(vector) != self.config.vector_size:
            raise EmbeddingProviderError(
                (
                    f"{self.config.provider} embedding dimension mismatch: "
                    f"expected {self.config.vector_size}, got {len(vector)}"
                ),
                provider=self.config.provider,
                error_type="embedding_dimension_mismatch",
            )
        return vector


def embedding_model_from_env(
    *,
    env: Mapping[str, str] | None = None,
    vector_size: int,
) -> EmbeddingModel:
    values = env if env is not None else os.environ
    if not _provider_embedding_configured(values):
        return DeterministicEmbeddingModel(dimension=vector_size)
    return OpenAICompatibleEmbeddingModel(
        OpenAICompatibleEmbeddingConfig.from_env(env=values, vector_size=vector_size),
        env=values,
    )


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def _provider_embedding_configured(values: Mapping[str, str]) -> bool:
    if values.get("NEWS_EMBEDDING_PROVIDER"):
        return True
    return any(
        values.get(key)
        for key in (
            "NEWS_EMBEDDING_BASE_URL",
            "NEWS_EMBEDDING_MODEL",
            "NEWS_EMBEDDING_API_KEY_ENV",
        )
    )


def _normalize_provider(provider: str) -> str:
    normalized = provider.strip().lower().replace("_", "-")
    if not normalized:
        return "openai-compatible"
    return normalized


def _optional_int(value: str | None, *, default: int | None) -> int | None:
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise EmbeddingConfigurationError(f"invalid integer environment value: {value}") from exc
    if parsed <= 0:
        raise EmbeddingConfigurationError(f"integer environment value must be positive: {value}")
    return parsed


def _optional_int_required(value: str | None, *, default: int) -> int:
    parsed = _optional_int(value, default=default)
    return default if parsed is None else parsed


def _optional_float(value: str | None, *, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise EmbeddingConfigurationError(f"invalid float environment value: {value}") from exc
    if parsed <= 0:
        raise EmbeddingConfigurationError(f"float environment value must be positive: {value}")
    return parsed


def _embedding_item_sort_key(indexed_item: tuple[int, Any]) -> int:
    fallback_index, item = indexed_item
    if isinstance(item, dict):
        provider_index = item.get("index")
        if isinstance(provider_index, int) and not isinstance(provider_index, bool):
            return provider_index
    return fallback_index


def _coerce_float(value: Any, *, provider: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EmbeddingProviderError(
            f"{provider} embedding vector contains non-numeric values",
            provider=provider,
            error_type="provider_response_shape_invalid",
        )
    return float(value)


def _error_type_from_http_status(status_code: int) -> str:
    if status_code in (401, 403):
        return "invalid_api_key"
    if status_code == 404:
        return "invalid_model"
    if status_code == 408:
        return "provider_timeout"
    if status_code == 429:
        return "rate_limited"
    if 500 <= status_code <= 599:
        return "provider_server_error"
    if 400 <= status_code <= 499:
        return "provider_client_error"
    return "unknown_embedding_error"


def _urlopen_transport(request: Request, timeout_seconds: float) -> bytes:
    with urlopen(request, timeout=timeout_seconds) as response:
        return response.read()
