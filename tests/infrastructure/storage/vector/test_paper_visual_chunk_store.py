from __future__ import annotations

from pathlib import Path

from business.research.document.models import PaperChunk
from infrastructure.storage.vector.fake_store import InMemoryVectorStore
from infrastructure.storage.vector.paper_visual_chunk_store import PaperVisualChunkStore


class _FakeVisualEmbedding:
    dimension = 3

    def embed_text(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0] if "architecture" in text.lower() else [0.0, 1.0, 0.0]

    def embed_image(self, image_path: str) -> list[float]:
        name = Path(image_path).name
        return [1.0, 0.0, 0.0] if "arch" in name else [0.0, 1.0, 0.0]

    def embed_images(self, image_paths: list[str]) -> list[list[float]]:
        return [self.embed_image(path) for path in image_paths]


def _chunk(
    chunk_id: str,
    *,
    chunk_type: str = "figure",
    image_ref: str = "",
    paper_id: str = "p1",
) -> PaperChunk:
    return PaperChunk(
        chunk_id=chunk_id,
        paper_id=paper_id,
        parse_source="latex",
        chunk_type=chunk_type,  # type: ignore[arg-type]
        section_title="Model Architecture",
        section_role=["method"],
        section_index=2,
        has_figure=chunk_type == "figure",
        figure_id="fig1" if chunk_type == "figure" else "",
        content="[Figure fig1]\nCaption:\nTransformer architecture.",
        metadata={
            "image_ref": image_ref,
            "source_locator": "paper://p1/pdf#page=3&pdf_rect=10,20,300,400",
            "content_sources": ["caption", "nearby_context"],
        },
    )


def test_visual_store_indexes_only_figure_chunks_with_images(tmp_path):
    arch_image = tmp_path / "arch.png"
    arch_image.write_bytes(b"not-a-real-image")
    table_image = tmp_path / "table.png"
    table_image.write_bytes(b"not-a-real-image")
    store = PaperVisualChunkStore(InMemoryVectorStore(), _FakeVisualEmbedding())
    store.ensure_collection()

    store.index_chunks([
        _chunk("fig-1", image_ref=str(arch_image)),
        _chunk("para-1", chunk_type="paragraph", image_ref=str(table_image)),
        _chunk("fig-no-image", image_ref=""),
    ])

    hits = store.search_visual_chunks("p1", "architecture diagram", limit=5)

    assert [hit.chunk_id for hit in hits] == ["fig-1"]
    assert hits[0].metadata["image_ref"] == str(arch_image)
    assert hits[0].metadata["visual_indexed"] is True


def test_visual_store_delete_paper_chunks(tmp_path):
    image_path = tmp_path / "arch.png"
    image_path.write_bytes(b"not-a-real-image")
    store = PaperVisualChunkStore(InMemoryVectorStore(), _FakeVisualEmbedding())
    store.ensure_collection()
    store.index_chunks([_chunk("fig-1", image_ref=str(image_path))])

    store.delete_paper_chunks("p1")

    assert store.search_visual_chunks("p1", "architecture diagram", limit=5) == []


def test_visual_store_resolves_image_ref_under_paper_root(tmp_path):
    image_path = tmp_path / "p1" / "figures" / "arch.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"not-a-real-image")
    store = PaperVisualChunkStore(
        InMemoryVectorStore(),
        _FakeVisualEmbedding(),
        image_root=tmp_path,
    )
    store.ensure_collection()

    store.index_chunks([_chunk("fig-1", image_ref="figures/arch.png")])

    hits = store.search_visual_chunks("p1", "architecture diagram", limit=5)
    assert [hit.chunk_id for hit in hits] == ["fig-1"]


def test_visual_store_resolves_windows_style_newsroom_image_ref(tmp_path, monkeypatch):
    image_path = tmp_path / ".newsroom" / "papers" / "p1" / "figures" / "arch.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"not-a-real-image")
    monkeypatch.chdir(tmp_path)
    store = PaperVisualChunkStore(
        InMemoryVectorStore(),
        _FakeVisualEmbedding(),
        image_root=tmp_path / ".newsroom" / "papers",
    )
    store.ensure_collection()

    store.index_chunks([
        _chunk("fig-1", image_ref=".newsroom\\papers\\p1\\figures\\arch.png")
    ])

    hits = store.search_visual_chunks("p1", "architecture diagram", limit=5)
    assert [hit.chunk_id for hit in hits] == ["fig-1"]


def test_visual_store_resolves_prefixed_newsroom_ref_from_workspace(tmp_path, monkeypatch):
    image_path = tmp_path / ".newsroom" / "papers" / "p1" / "figures" / "arch.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"not-a-real-image")
    monkeypatch.chdir(tmp_path)
    store = PaperVisualChunkStore(
        InMemoryVectorStore(),
        _FakeVisualEmbedding(),
        image_root=tmp_path / ".newsroom" / "papers",
    )
    store.ensure_collection()

    store.index_chunks([
        _chunk(
            "fig-1",
            image_ref="workspace-copy\\.newsroom\\papers\\p1\\figures\\arch.png",
        )
    ])

    hits = store.search_visual_chunks("p1", "architecture diagram", limit=5)
    assert [hit.chunk_id for hit in hits] == ["fig-1"]
