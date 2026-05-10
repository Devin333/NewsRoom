from __future__ import annotations

import os
from collections import defaultdict
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient, models

from storage.vector.embeddings import DeterministicEmbeddingModel
from storage.vector.models import VectorDocument, VectorSearchQuery, VectorSearchResult


DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
DEFAULT_VECTOR_SIZE = 64


class QdrantVectorStore:
    def __init__(
        self,
        client: QdrantClient,
        *,
        embedding_model: DeterministicEmbeddingModel | None = None,
        vector_size: int = DEFAULT_VECTOR_SIZE,
    ) -> None:
        self.client = client
        self.embedding_model = embedding_model or DeterministicEmbeddingModel(dimension=vector_size)
        self.vector_size = vector_size

    def upsert_documents(self, docs: list[VectorDocument]) -> None:
        grouped: dict[str, list[VectorDocument]] = defaultdict(list)
        for doc in docs:
            grouped[doc.collection].append(doc)

        for collection, collection_docs in grouped.items():
            self._ensure_collection(collection)
            points = []
            for doc in collection_docs:
                vector = doc.vector or self.embedding_model.embed_text(doc.text)
                points.append(
                    models.PointStruct(
                        id=str(uuid5(NAMESPACE_URL, f"{collection}:{doc.document_id}")),
                        vector=vector,
                        payload=doc.to_payload(),
                    )
                )
            self.client.upsert(collection_name=collection, points=points, wait=True)

    def search(self, query: VectorSearchQuery) -> list[VectorSearchResult]:
        query_vector = query.vector or self.embedding_model.embed_text(query.text)
        response = self.client.query_points(
            collection_name=query.collection,
            query=query_vector,
            query_filter=_qdrant_filter(query.filters),
            limit=query.limit,
            with_payload=True,
            score_threshold=query.score_threshold,
        )
        points = getattr(response, "points", response)
        return [
            VectorSearchResult.from_payload(score=point.score, payload=dict(point.payload or {}))
            for point in points
        ]

    def _ensure_collection(self, collection: str) -> None:
        if self.client.collection_exists(collection):
            return
        self.client.create_collection(
            collection_name=collection,
            vectors_config=models.VectorParams(size=self.vector_size, distance=models.Distance.COSINE),
        )


def qdrant_store_from_env(
    *,
    embedding_model: DeterministicEmbeddingModel | None = None,
) -> QdrantVectorStore:
    vector_size = int(os.environ.get("NEWS_VECTOR_SIZE", DEFAULT_VECTOR_SIZE))
    url = os.environ.get("NEWS_QDRANT_URL", DEFAULT_QDRANT_URL)
    client = QdrantClient(url=url)
    return QdrantVectorStore(client, embedding_model=embedding_model, vector_size=vector_size)


def _qdrant_filter(filters: dict[str, Any]) -> models.Filter | None:
    if not filters:
        return None
    return models.Filter(
        must=[
            models.FieldCondition(key=key, match=models.MatchValue(value=value))
            for key, value in filters.items()
        ]
    )
