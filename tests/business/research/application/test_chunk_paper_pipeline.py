from __future__ import annotations

import json
from dataclasses import dataclass

from business.research.application.chunk_paper_pipeline import ChunkPaperPipeline
from business.research.document.chunk_manifest import ChunkManifestManager
from business.research.document.models import PaperChunk
from tests.business.research.document.helpers import make_doc, make_figure, make_section


@dataclass(frozen=True)
class _SourcePackage:
    content: bytes
    checksum: str = "sha256-test"


class _SourceFetcher:
    def fetch_source_package(self, source_id: str) -> _SourcePackage:
        return _SourcePackage(content=f"source:{source_id}".encode())


class _DocumentParser:
    def parse(self, paper_id: str, source_bytes: bytes):
        return make_doc(
            paper_id=paper_id,
            sections=[
                make_section("s0", "Abstract", "Abstract."),
                make_section("s1", "Introduction", "Intro."),
                make_section("s2", "Method", "First method paragraph.\n\nSecond method paragraph."),
                make_section("s3", "Experiments", "Experiment results."),
            ],
        )


class _DocumentParserWithFigure:
    def parse(self, paper_id: str, source_bytes: bytes):
        return make_doc(
            paper_id=paper_id,
            sections=[
                make_section("s0", "Abstract", "Abstract."),
                make_section("s1", "Introduction", "Figure 1 shows the model architecture."),
                make_section("s2", "Method", "The architecture uses encoder decoder blocks."),
                make_section("s3", "Experiments", "Experiment results."),
            ],
        ).model_copy(update={
            "figures": [
                make_figure("fig1", "Figure 1: model architecture.").model_copy(
                    update={"image_ref": "figures/arch.png"}
                )
            ]
        })


class _ChunkStore:
    def __init__(self) -> None:
        self.chunks: list[PaperChunk] = []

    def ensure_collection(self) -> None:
        return None

    def index_chunks(self, chunks: list[PaperChunk]) -> None:
        self.chunks = list(chunks)


class _ChunkRepository:
    def __init__(self) -> None:
        self.chunks: list[PaperChunk] = []

    def save_chunks(self, chunks: list[PaperChunk]) -> None:
        self.chunks = list(chunks)

    def delete_paper_chunks(self, paper_id: str) -> None:
        self.chunks = [chunk for chunk in self.chunks if chunk.paper_id != paper_id]


class _VisualChunkIndexer:
    def __init__(self) -> None:
        self.ensure_called = False
        self.chunks: list[PaperChunk] = []

    def ensure_collection(self) -> None:
        self.ensure_called = True

    def index_chunks(self, chunks: list[PaperChunk]) -> None:
        self.chunks = list(chunks)

    def delete_paper_chunks(self, paper_id: str) -> None:
        self.chunks = [chunk for chunk in self.chunks if chunk.paper_id != paper_id]


class _FieldChunkIndexer(_VisualChunkIndexer):
    pass


class _VisualDescriber:
    def describe_chunks(self, chunks: list[PaperChunk]) -> list[PaperChunk]:
        return [
            chunk.model_copy(update={
                "metadata": {
                    **chunk.metadata,
                    "visual_description": "The image shows encoder decoder blocks.",
                },
                "content": f"{chunk.content}\n\nVisual Description:\nThe image shows encoder decoder blocks.",
            })
            if chunk.chunk_type == "figure"
            else chunk
            for chunk in chunks
        ]


def test_chunk_pipeline_writes_chunk_manifest(tmp_path):
    store = _ChunkStore()
    repo = _ChunkRepository()
    manifest_path = tmp_path / "chunk_manifest.json"
    pipeline = ChunkPaperPipeline(
        store,  # type: ignore[arg-type]
        repo,
        _SourceFetcher(),
        _DocumentParser(),
        chunk_manifest=ChunkManifestManager(manifest_path),
        with_propositions=False,
    )

    result = pipeline.run("2501.00001")

    assert result.chunk_manifest_path == str(manifest_path)
    assert manifest_path.exists()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["paper_id"] == "2501.00001"
    assert payload["chunks"]
    assert store.chunks
    assert repo.chunks
    assert all(chunk.metadata.get("semantic_key") for chunk in store.chunks)
    assert {entry["chunk_id"] for entry in payload["chunks"]} == {
        chunk.chunk_id for chunk in store.chunks
    }


def test_chunk_pipeline_optionally_indexes_visual_chunks(tmp_path):
    store = _ChunkStore()
    repo = _ChunkRepository()
    visual_indexer = _VisualChunkIndexer()
    pipeline = ChunkPaperPipeline(
        store,  # type: ignore[arg-type]
        repo,
        _SourceFetcher(),
        _DocumentParser(),
        visual_chunk_indexer=visual_indexer,
        chunk_manifest=ChunkManifestManager(tmp_path / "chunk_manifest.json"),
        with_propositions=False,
    )

    pipeline.run("2501.00001")

    assert visual_indexer.ensure_called is True
    assert visual_indexer.chunks == store.chunks


def test_chunk_pipeline_optionally_indexes_field_chunks(tmp_path):
    store = _ChunkStore()
    repo = _ChunkRepository()
    field_indexer = _FieldChunkIndexer()
    pipeline = ChunkPaperPipeline(
        store,  # type: ignore[arg-type]
        repo,
        _SourceFetcher(),
        _DocumentParser(),
        field_chunk_indexer=field_indexer,
        chunk_manifest=ChunkManifestManager(tmp_path / "chunk_manifest.json"),
        with_propositions=False,
    )

    pipeline.run("2501.00001")

    assert field_indexer.ensure_called is True
    assert field_indexer.chunks == store.chunks


def test_chunk_pipeline_describes_visual_chunks_before_indexing(tmp_path):
    store = _ChunkStore()
    repo = _ChunkRepository()
    pipeline = ChunkPaperPipeline(
        store,  # type: ignore[arg-type]
        repo,
        _SourceFetcher(),
        _DocumentParserWithFigure(),
        visual_chunk_describer=_VisualDescriber(),  # type: ignore[arg-type]
        chunk_manifest=ChunkManifestManager(tmp_path / "chunk_manifest.json"),
        with_propositions=False,
    )

    result = pipeline.run("2501.00001")

    stored_figure = next(chunk for chunk in store.chunks if chunk.chunk_type == "figure")
    repo_figure = next(chunk for chunk in repo.chunks if chunk.chunk_type == "figure")
    assert result.visual_described_chunks == 1
    assert stored_figure.metadata["visual_description"] == "The image shows encoder decoder blocks."
    assert repo_figure.metadata["visual_description"] == "The image shows encoder decoder blocks."
