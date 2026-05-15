"""Vector memory storage boundary."""

from storage.vector.embeddings import (
    DeterministicEmbeddingModel,
    EmbeddingConfigurationError,
    EmbeddingModel,
    EmbeddingProviderError,
    FakeEmbeddingAdapter,
    OpenAICompatibleEmbeddingConfig,
    OpenAICompatibleEmbeddingModel,
    embedding_model_from_env,
)
from storage.vector.fake_store import InMemoryVectorStore
from storage.vector.models import (
    VectorCollectionStatus,
    VectorDocument,
    VectorPayloadIndexStatus,
    VectorSearchQuery,
    VectorSearchResult,
)
from storage.vector.qdrant_store import QdrantVectorStore, qdrant_store_from_env

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
