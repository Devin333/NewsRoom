from __future__ import annotations

import json
from pathlib import Path

from backend.research.document.models import PaperChunk
from backend.research.rag.visual.describe_visual_artifacts import describe_visual_artifacts


class _FakeDescriber:
    def describe_chunks(self, chunks: list[PaperChunk]) -> list[PaperChunk]:
        out: list[PaperChunk] = []
        for chunk in chunks:
            if chunk.chunk_type == "figure":
                metadata = dict(chunk.metadata)
                metadata.update({
                    "visual_description": "The figure shows encoder decoder blocks.",
                    "visual_description_status": "ok",
                    "visual_description_model": "fake-vision",
                    "visual_description_source": "test",
                    "visual_description_image_path": "/tmp/fig.png",
                })
                chunk = chunk.model_copy(update={"metadata": metadata})
            out.append(chunk)
        return out


def test_describe_visual_artifacts_writes_visual_metadata(tmp_path: Path) -> None:
    paper_dir = tmp_path / "papers" / "p1"
    paper_dir.mkdir(parents=True)
    document_path = paper_dir / "research_document.json"
    document_path.write_text(
        json.dumps(_research_document_payload(), ensure_ascii=False),
        encoding="utf-8",
    )

    result = describe_visual_artifacts(
        papers_dir=tmp_path / "papers",
        image_root=tmp_path / "papers",
        write=True,
        describer=_FakeDescriber(),  # type: ignore[arg-type]
    )

    assert result.papers_seen == 1
    assert result.papers_written == 1
    assert result.visual_chunks_seen == 1
    assert result.visual_chunks_described == 1
    payload = json.loads(document_path.read_text(encoding="utf-8"))
    figure_metadata = payload["figures"][0]["metadata"]
    assert figure_metadata["visual_description"] == "The figure shows encoder decoder blocks."
    assert figure_metadata["visual_description_status"] == "ok"
    assert payload["metadata"]["visual_described_figures"] == 1


def _research_document_payload() -> dict:
    return {
        "paper_id": "p1",
        "source_hash": "hash",
        "sections": [
            {
                "section_id": "abstract",
                "title": "Abstract",
                "level": 1,
                "text": "This paper introduces a visual architecture.",
                "source_ref": "paper://p1/abstract",
            },
            {
                "section_id": "intro",
                "title": "Introduction",
                "level": 1,
                "text": "The visual architecture is shown in Figure 1. It improves retrieval.",
                "source_ref": "paper://p1/intro",
            },
            {
                "section_id": "method",
                "title": "Method",
                "level": 1,
                "text": "The model architecture uses encoder and decoder blocks.",
                "source_ref": "paper://p1/method",
            },
            {
                "section_id": "results",
                "title": "Results",
                "level": 1,
                "text": "Results text.",
                "source_ref": "paper://p1/results",
            },
        ],
        "figures": [
            {
                "figure_id": "fig1",
                "caption": "Figure 1: visual architecture overview.",
                "source_ref": "paper://p1/fig1",
                "image_ref": "figures/arch.png",
                "page": 1,
            }
        ],
        "tables": [],
        "equations": [],
        "references": [],
        "lineage": {
            "source_refs": ["paper://p1"],
            "source_hash": "hash",
            "artifact_refs": [],
            "metadata": {},
        },
        "metadata": {"parse_source": "nougat"},
    }
