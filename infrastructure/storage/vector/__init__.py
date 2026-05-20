"""Vector memory storage boundary."""

from infrastructure.storage.vector.embeddings import (
    DeterministicEmbeddingModel,
    EmbeddingConfigurationError,
    EmbeddingModel,
    EmbeddingProviderError,
    FakeEmbeddingAdapter,
    OpenAICompatibleEmbeddingConfig,
    OpenAICompatibleEmbeddingModel,
    embedding_model_from_env,
)
from infrastructure.storage.vector.fake_store import InMemoryVectorStore
from infrastructure.storage.vector.models import (
    VectorCollectionStatus,
    VectorDocument,
    VectorPayloadIndexStatus,
    VectorSearchQuery,
    VectorSearchResult,
)

try:
    from infrastructure.storage.vector.qdrant_store import QdrantVectorStore, qdrant_store_from_env
except ModuleNotFoundError as exc:
    _QDRANT_IMPORT_ERROR = exc

    class QdrantVectorStore:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs) -> None:
            raise ModuleNotFoundError(
                "qdrant-client is required for QdrantVectorStore. Install with `python -m pip install -e \".[qdrant]\"` or `python -m pip install -e \".[dev]\"`."
            ) from _QDRANT_IMPORT_ERROR

    def qdrant_store_from_env(*args, **kwargs):  # type: ignore[no-redef]
        raise ModuleNotFoundError(
            "qdrant-client is required for memory/vector features. Install with `python -m pip install -e \".[qdrant]\"` or `python -m pip install -e \".[dev]\"`."
        ) from _QDRANT_IMPORT_ERROR

__all__ = [
    "DeterministicEmbeddingModel",
    "EmbeddingConfigurationError",
    "EmbeddingModel",
    "EmbeddingProviderError",
    "FakeEmbeddingAdapter",
    "InMemoryVectorStore",
    "OpenAICompatibleEmbeddingConfig",
    "OpenAICompatibleEmbeddingModel",
    "QdrantVectorStore",
    "VectorCollectionStatus",
    "VectorDocument",
    "VectorPayloadIndexStatus",
    "VectorSearchQuery",
    "VectorSearchResult",
    "embedding_model_from_env",
    "qdrant_store_from_env",
]
