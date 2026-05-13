from __future__ import annotations

import os
from collections import defaultdict
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient, models

from storage.vector.embeddings import EmbeddingModel, embedding_model_from_env
from storage.vector.models import (
    VectorCollectionStatus,
    VectorDocument,
    VectorSearchQuery,
    VectorSearchResult,
)


DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
DEFAULT_VECTOR_SIZE = 64


class QdrantVectorStore:
    def __init__(
        self,
        client: QdrantClient,
        *,
        embedding_model: EmbeddingModel | None = None,
        vector_size: int = DEFAULT_VECTOR_SIZE,
    ) -> None:
        self.client = client
        self.embedding_model = embedding_model or embedding_model_from_env(vector_size=vector_size)
        self.vector_size = vector_size

    def upsert_documents(self, docs: list[VectorDocument]) -> None:
        grouped: dict[str, list[VectorDocument]] = defaultdict(list)
        for doc in docs:
            grouped[doc.collection].append(doc)

        for collection, collection_docs in grouped.items():
            self._ensure_collection(collection)
            points = []
            embedded_vectors = iter(
                self.embedding_model.embed_texts([doc.text for doc in collection_docs if doc.vector is None])
            )
            for doc in collection_docs:
                vector = doc.vector or next(embedded_vectors)
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

    def get_document(self, collection: str, document_id: str) -> VectorSearchResult | None:
        response = self.client.scroll(
            collection_name=collection,
            scroll_filter=_qdrant_filter({"document_id": document_id}),
            limit=1,
            with_payload=True,
            with_vectors=False,
        )
        points = response[0] if isinstance(response, tuple) else getattr(response, "points", response)
        if not points:
            return None
        return VectorSearchResult.from_payload(score=1.0, payload=dict(points[0].payload or {}))

    def ensure_collections(self, collections: list[str]) -> list[VectorCollectionStatus]:
        statuses = []
        for collection in collections:
            existed_before = self.client.collection_exists(collection)
            created = False
            if not existed_before:
                self._create_collection(collection)
                created = True
            statuses.append(
                VectorCollectionStatus(
                    collection=collection,
                    vector_size=self.vector_size,
                    existed_before=existed_before,
                    created=created,
                )
            )
        return statuses

    def _ensure_collection(self, collection: str) -> None:
        if self.client.collection_exists(collection):
            return
        self._create_collection(collection)

    def _create_collection(self, collection: str) -> None:
        self.client.create_collection(
            collection_name=collection,
            vectors_config=models.VectorParams(size=self.vector_size, distance=models.Distance.COSINE),
        )


def qdrant_store_from_env(
    *,
    embedding_model: EmbeddingModel | None = None,
    env: dict[str, str] | None = None,
) -> QdrantVectorStore:
    values = env if env is not None else os.environ
    vector_size = _vector_size_from_env(values)
    url = values.get("NEWS_QDRANT_URL", DEFAULT_QDRANT_URL)
    client = QdrantClient(url=url)
    resolved_embedding_model = embedding_model or embedding_model_from_env(env=values, vector_size=vector_size)
    return QdrantVectorStore(client, embedding_model=resolved_embedding_model, vector_size=vector_size)


def _qdrant_filter(filters: dict[str, Any]) -> models.Filter | None:
    if not filters:
        return None
    return models.Filter(
        must=[
            models.FieldCondition(key=key, match=models.MatchValue(value=value))
            for key, value in filters.items()
        ]
    )


def _vector_size_from_env(values: Mapping[str, str]) -> int:
    if values.get("NEWS_VECTOR_SIZE"):
        return int(values["NEWS_VECTOR_SIZE"])
    if values.get("NEWS_EMBEDDING_DIMENSIONS"):
        return int(values["NEWS_EMBEDDING_DIMENSIONS"])
    return DEFAULT_VECTOR_SIZE
