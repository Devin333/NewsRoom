from __future__ import annotations

import builtins
from pathlib import Path
from typing import Any

import pytest

from business.research.document.models import PaperChunk
from interfaces.composition import research as research_composition
from interfaces.composition.research_errors import ResearchRuntimeUnavailableError
from interfaces.composition.research_settings import ResearchRAGSettings


def _settings(
    tmp_path: Path,
    *,
    backend: str = "local",
    qdrant_url: str | None = None,
) -> ResearchRAGSettings:
    return ResearchRAGSettings(
        backend=backend,
        local_root=(tmp_path / "chunks").resolve(),
        qdrant_url=qdrant_url,
        collection="research_test_chunks",
        vector_size=32,
        max_rounds=2,
        max_replans=1,
        max_queries=4,
        max_source_reads=8,
        max_memory_hits=2,
        max_context_items=4,
        max_context_tokens=1024,
        max_worker_calls=4,
    )


def _chunk(chunk_id: str = "chunk-1") -> PaperChunk:
    return PaperChunk(
        chunk_id=chunk_id,
        paper_id="paper-1",
        parse_source="latex",
        section_title="Method",
        section_role=["method"],
        content="bounded document evidence",
        metadata={
            "source_ref": "paper://paper-1/method",
            "run_id": "run-1",
        },
    )


def test_local_chunk_backend_does_not_import_qdrant_and_survives_reopen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    original_import = builtins.__import__

    def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "qdrant_client" or name.startswith(
            "infrastructure.storage.vector"
        ):
            raise AssertionError("local Research RAG must not import Qdrant")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    first, resources = research_composition._build_research_chunk_store(settings)
    first.index_chunks([_chunk()])  # type: ignore[attr-defined]
    second, reopened_resources = research_composition._build_research_chunk_store(
        settings
    )

    assert resources == ()
    assert reopened_resources == ()
    assert [chunk.chunk_id for chunk in second.list_chunks("paper-1")] == [
        "chunk-1"
    ]
    assert (settings.local_root / f"{settings.collection}.json").is_file()


def test_qdrant_chunk_backend_uses_validated_settings_and_returns_client_resource(
    tmp_path: Path,
) -> None:
    settings = _settings(
        tmp_path,
        backend="qdrant",
        qdrant_url="http://qdrant.internal:6333",
    )
    captured: dict[str, Any] = {}
    client = _FakeQdrantClient()

    def client_factory(*, url: str) -> _FakeQdrantClient:
        captured["url"] = url
        return client

    def embedding_factory(*, vector_size: int) -> _FakeEmbedding:
        captured["vector_size"] = vector_size
        return _FakeEmbedding(vector_size)

    store, resources = research_composition._build_research_chunk_store(
        settings,
        qdrant_client_factory=client_factory,
        embedding_model_factory=embedding_factory,
    )

    assert captured == {
        "url": "http://qdrant.internal:6333",
        "vector_size": 32,
    }
    assert resources == (client,)
    assert client.collections == {"research_test_chunks"}
    assert {field for _collection, field in client.payload_indexes} >= {
        "paper_id",
        "run_id",
        "tenant_id",
    }
    assert store.list_chunks("paper-1") == []


def test_qdrant_failure_is_typed_and_does_not_fall_back_to_local(
    tmp_path: Path,
) -> None:
    settings = _settings(
        tmp_path,
        backend="qdrant",
        qdrant_url="http://qdrant.internal:6333",
    )
    client = _FakeQdrantClient(fail_collection=True)

    with pytest.raises(ResearchRuntimeUnavailableError) as exc_info:
        research_composition._build_research_chunk_store(
            settings,
            qdrant_client_factory=lambda **_kwargs: client,
            embedding_model_factory=lambda **_kwargs: _FakeEmbedding(32),
        )

    assert exc_info.value.capabilities == ("research.rag.vector_backend",)
    assert exc_info.value.retryable is True
    assert client.close_calls == 1
    assert settings.local_root.exists() is False


def test_missing_qdrant_dependency_is_typed_without_local_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(
        tmp_path,
        backend="qdrant",
        qdrant_url="http://qdrant.internal:6333",
    )
    original_import = builtins.__import__

    def missing_qdrant(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "qdrant_client":
            raise ModuleNotFoundError("private optional dependency detail")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_qdrant)

    with pytest.raises(ResearchRuntimeUnavailableError) as exc_info:
        research_composition._build_research_chunk_store(settings)

    assert exc_info.value.capabilities == ("research.rag.vector_backend",)
    assert "private optional dependency detail" not in str(exc_info.value)
    assert settings.local_root.exists() is False


class _FakeEmbedding:
    def __init__(self, dimension: int) -> None:
        self.dimension = dimension

    def embed_text(self, _text: str) -> list[float]:
        return [0.0] * self.dimension

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(text) for text in texts]


class _FakeCollectionInfo:
    payload_schema: dict[str, Any] = {}


class _FakeQdrantClient:
    def __init__(self, *, fail_collection: bool = False) -> None:
        self.fail_collection = fail_collection
        self.collections: set[str] = set()
        self.payload_indexes: list[tuple[str, str]] = []
        self.close_calls = 0

    def collection_exists(self, collection: str) -> bool:
        if self.fail_collection:
            raise OSError("private qdrant transport failure")
        return collection in self.collections

    def create_collection(self, *, collection_name: str, **_kwargs: Any) -> None:
        self.collections.add(collection_name)

    def get_collection(self, _collection: str) -> _FakeCollectionInfo:
        return _FakeCollectionInfo()

    def create_payload_index(
        self,
        *,
        collection_name: str,
        field_name: str,
        **_kwargs: Any,
    ) -> None:
        self.payload_indexes.append((collection_name, field_name))

    def scroll(self, **_kwargs: Any) -> tuple[list[Any], None]:
        return [], None

    def close(self) -> None:
        self.close_calls += 1
