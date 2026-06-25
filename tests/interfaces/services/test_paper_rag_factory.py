from __future__ import annotations

from interfaces.services import paper_rag_factory


class _FakeStore:
    def ensure_collection(self) -> None:
        pass


class _FakeRepo:
    pass


class _FakeFetcher:
    pass


class _FakeParser:
    pass


class _FakeVisualStore:
    def __init__(self) -> None:
        self.ensure_called = False

    def ensure_collection(self) -> None:
        self.ensure_called = True


class _FakePipeline:
    last_kwargs = {}

    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        _FakePipeline.last_kwargs = kwargs


class _FakeRetriever:
    last_kwargs = {}

    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        _FakeRetriever.last_kwargs = kwargs


class _FakeSession:
    last_kwargs = {}

    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        _FakeSession.last_kwargs = kwargs


def test_build_visual_chunk_store_returns_none_when_visual_embedding_disabled(monkeypatch):
    monkeypatch.setattr(paper_rag_factory, "paper_visual_chunk_store_from_env", lambda: None)

    assert paper_rag_factory.build_visual_chunk_store() is None


def test_build_visual_chunk_store_ensures_configured_store(monkeypatch):
    visual_store = _FakeVisualStore()
    monkeypatch.setattr(
        paper_rag_factory,
        "paper_visual_chunk_store_from_env",
        lambda: visual_store,
    )

    assert paper_rag_factory.build_visual_chunk_store() is visual_store
    assert visual_store.ensure_called is True


def test_chunk_pipeline_receives_visual_chunk_indexer(monkeypatch):
    visual_store = _FakeVisualStore()
    monkeypatch.setattr(paper_rag_factory, "ChunkPaperPipeline", _FakePipeline)
    monkeypatch.setattr(paper_rag_factory, "build_chunk_store", lambda: _FakeStore())
    monkeypatch.setattr(paper_rag_factory, "build_chunk_repository", lambda: _FakeRepo())
    monkeypatch.setattr(paper_rag_factory, "build_field_chunk_store", lambda: _FakeStore())
    monkeypatch.setattr(paper_rag_factory, "build_visual_chunk_store", lambda: visual_store)
    monkeypatch.setattr(paper_rag_factory, "ArxivSourceConnector", _FakeFetcher)
    monkeypatch.setattr(paper_rag_factory, "ArxivDocumentParser", _FakeParser)

    paper_rag_factory.build_chunk_pipeline()

    assert _FakePipeline.last_kwargs["visual_chunk_indexer"] is visual_store


def test_retriever_and_session_receive_visual_store(monkeypatch):
    visual_store = _FakeVisualStore()
    monkeypatch.setattr(paper_rag_factory, "ResearchRetriever", _FakeRetriever)
    monkeypatch.setattr(paper_rag_factory, "PaperRAGSession", _FakeSession)
    monkeypatch.setattr(paper_rag_factory, "build_chunk_store", lambda: _FakeStore())
    monkeypatch.setattr(paper_rag_factory, "build_field_chunk_store", lambda: _FakeStore())
    monkeypatch.setattr(paper_rag_factory, "build_visual_chunk_store", lambda: visual_store)

    paper_rag_factory.build_research_retriever(with_reranker=False)
    paper_rag_factory.build_paper_rag_session(with_reranker=False)

    assert _FakeRetriever.last_kwargs["visual_store"] is visual_store
    assert _FakeSession.last_kwargs["visual_store"] is visual_store
