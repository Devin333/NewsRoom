from __future__ import annotations

import os
from typing import Any

# Default to the bge-reranker-v2-m3 cross-encoder (multilingual, strong on zh+en).
DEFAULT_RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"


class CrossEncoderReranker:
    """sentence-transformers CrossEncoder reranker. Implements RerankerPort.

    Model is loaded lazily on first score() call so importing this module stays cheap
    and the heavy weights load only when reranking is actually used.
    """

    def __init__(
        self,
        model_name: str | None = None,
        *,
        device: str | None = None,
        max_length: int = 512,
        batch_size: int = 16,
    ) -> None:
        self._model_name = model_name or os.getenv("NEWS_RERANKER_MODEL", DEFAULT_RERANKER_MODEL)
        # CUDA kernels on this host are incompatible; default to CPU unless overridden.
        self._device = device or os.getenv("NEWS_RERANKER_DEVICE", "cpu")
        self._max_length = max_length
        self._batch_size = batch_size
        self._model: Any | None = None

    def _ensure_model(self) -> Any:
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(
                self._model_name, max_length=self._max_length, device=self._device
            )
        return self._model

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        model = self._ensure_model()
        pairs = [(query, passage) for passage in passages]
        scores = model.predict(pairs, batch_size=self._batch_size)
        return [float(s) for s in scores]


__all__ = ["CrossEncoderReranker", "DEFAULT_RERANKER_MODEL"]
