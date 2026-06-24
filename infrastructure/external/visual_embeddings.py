from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping

from infrastructure.storage.vector.embeddings import (
    EmbeddingConfigurationError,
    EmbeddingProviderError,
)


DEFAULT_VISUAL_EMBEDDING_MODEL = "clip-ViT-B-32"
DEFAULT_VISUAL_VECTOR_SIZE = 512


@dataclass(frozen=True)
class SentenceTransformerVisualEmbeddingConfig:
    provider: str = "sentence-transformers"
    model: str = DEFAULT_VISUAL_EMBEDDING_MODEL
    vector_size: int = DEFAULT_VISUAL_VECTOR_SIZE
    device: str | None = None

    def __post_init__(self) -> None:
        if self.provider.strip().lower().replace("_", "-") != "sentence-transformers":
            raise EmbeddingConfigurationError(
                f"unsupported visual embedding provider: {self.provider}"
            )
        if not self.model.strip():
            raise EmbeddingConfigurationError("visual embedding model is required")
        if self.vector_size <= 0:
            raise EmbeddingConfigurationError("visual vector size must be positive")

    @classmethod
    def from_env(
        cls,
        *,
        env: Mapping[str, str] | None = None,
    ) -> "SentenceTransformerVisualEmbeddingConfig":
        values = env if env is not None else os.environ
        return cls(
            provider=values.get("NEWS_VISUAL_EMBEDDING_PROVIDER", "sentence-transformers"),
            model=values.get("NEWS_VISUAL_EMBEDDING_MODEL", DEFAULT_VISUAL_EMBEDDING_MODEL),
            vector_size=_optional_int(
                values.get("NEWS_VISUAL_VECTOR_SIZE"),
                default=DEFAULT_VISUAL_VECTOR_SIZE,
            ),
            device=values.get("NEWS_VISUAL_EMBEDDING_DEVICE") or None,
        )


class SentenceTransformerVisualEmbeddingModel:
    """CLIP-style multimodal embedding adapter backed by sentence-transformers."""

    def __init__(self, config: SentenceTransformerVisualEmbeddingConfig) -> None:
        self.config = config
        try:
            from sentence_transformers import SentenceTransformer
        except ModuleNotFoundError as exc:
            raise EmbeddingConfigurationError(
                "sentence-transformers is required for NEWS_VISUAL_EMBEDDING_PROVIDER=sentence-transformers"
            ) from exc
        kwargs: dict[str, Any] = {}
        if config.device:
            kwargs["device"] = config.device
        self._model = SentenceTransformer(config.model, **kwargs)
        self.dimension = config.vector_size

    def embed_text(self, text: str) -> list[float]:
        return self._coerce_vector(self._encode(text))

    def embed_image(self, image_path: str) -> list[float]:
        return self.embed_images([image_path])[0]

    def embed_images(self, image_paths: list[str]) -> list[list[float]]:
        if not image_paths:
            return []
        try:
            from PIL import Image
        except ModuleNotFoundError as exc:
            raise EmbeddingConfigurationError(
                "Pillow is required for visual image embeddings"
            ) from exc

        images = []
        for image_path in image_paths:
            try:
                images.append(Image.open(image_path).convert("RGB"))
            except OSError as exc:
                raise EmbeddingProviderError(
                    f"could not open image for visual embedding: {image_path}",
                    provider=self.config.provider,
                    error_type="visual_image_open_failed",
                ) from exc
        try:
            raw_vectors = self._encode(images)
        finally:
            for image in images:
                image.close()
        return [self._coerce_vector(raw) for raw in raw_vectors]

    def _encode(self, value: Any) -> Any:
        try:
            return self._model.encode(
                value,
                convert_to_numpy=True,
                normalize_embeddings=True,
            )
        except Exception as exc:
            raise EmbeddingProviderError(
                "visual embedding provider request failed",
                provider=self.config.provider,
                error_type="visual_embedding_provider_error",
            ) from exc

    def _coerce_vector(self, raw: Any) -> list[float]:
        values = raw.tolist() if hasattr(raw, "tolist") else raw
        if not isinstance(values, list):
            raise EmbeddingProviderError(
                "visual embedding response is not a vector",
                provider=self.config.provider,
                error_type="provider_response_shape_invalid",
            )
        if values and isinstance(values[0], list):
            values = values[0]
        vector = [float(value) for value in values]
        if len(vector) != self.dimension:
            raise EmbeddingProviderError(
                f"visual embedding dimension mismatch: expected {self.dimension}, got {len(vector)}",
                provider=self.config.provider,
                error_type="embedding_dimension_mismatch",
            )
        return vector


def visual_embedding_model_from_env(
    *,
    env: Mapping[str, str] | None = None,
) -> SentenceTransformerVisualEmbeddingModel | None:
    values = env if env is not None else os.environ
    if not _visual_embedding_configured(values):
        return None
    return SentenceTransformerVisualEmbeddingModel(
        SentenceTransformerVisualEmbeddingConfig.from_env(env=values)
    )


def _visual_embedding_configured(values: Mapping[str, str]) -> bool:
    enabled = values.get("NEWS_VISUAL_EMBEDDING_ENABLED")
    if enabled is not None and enabled.strip().lower() in {"1", "true", "yes", "on"}:
        return True
    return any(
        values.get(key)
        for key in (
            "NEWS_VISUAL_EMBEDDING_PROVIDER",
            "NEWS_VISUAL_EMBEDDING_MODEL",
            "NEWS_VISUAL_VECTOR_SIZE",
        )
    )


def _optional_int(value: str | None, *, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise EmbeddingConfigurationError(f"invalid integer environment value: {value}") from exc
    if parsed <= 0:
        raise EmbeddingConfigurationError(f"integer environment value must be positive: {value}")
    return parsed


__all__ = [
    "DEFAULT_VISUAL_EMBEDDING_MODEL",
    "DEFAULT_VISUAL_VECTOR_SIZE",
    "SentenceTransformerVisualEmbeddingConfig",
    "SentenceTransformerVisualEmbeddingModel",
    "visual_embedding_model_from_env",
]
