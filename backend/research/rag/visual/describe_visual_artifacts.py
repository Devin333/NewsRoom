from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from backend.research.application.visual_chunk_describer import (
    OpenAICompatibleVisualChunkDescriber,
    VisualChunkDescriptionConfig,
)
from backend.research.document.chunker import PaperDocumentChunker
from backend.research.document.visual_document_sync import sync_visual_descriptions_to_document
from backend.research.domain.document import ResearchDocument


@dataclass(frozen=True)
class VisualDescriptionBatchResult:
    papers_seen: int
    papers_written: int
    visual_chunks_seen: int
    visual_chunks_described: int
    visual_chunks_skipped: int


def describe_visual_artifacts(
    *,
    papers_dir: Path,
    image_root: Path | None = None,
    write: bool = False,
    describer: OpenAICompatibleVisualChunkDescriber | None = None,
) -> VisualDescriptionBatchResult:
    """Describe figure/table images in parsed paper artifacts and optionally persist them."""
    paper_paths = sorted(papers_dir.glob("*/research_document.json"))
    if not paper_paths:
        return VisualDescriptionBatchResult(0, 0, 0, 0, 0)

    active_describer = describer or _build_describer(image_root=image_root or papers_dir)
    chunker = PaperDocumentChunker()
    papers_written = 0
    visual_chunks_seen = 0
    visual_chunks_described = 0
    visual_chunks_skipped = 0

    for path in paper_paths:
        document = _read_document(path)
        parse_source = str(document.metadata.get("parse_source") or "nougat")
        chunks = chunker.chunk(document, parse_source)  # type: ignore[arg-type]
        visual_chunks = [
            chunk for chunk in chunks
            if chunk.chunk_type in {"figure", "table"} and chunk.metadata.get("image_ref")
        ]
        visual_chunks_seen += len(visual_chunks)
        before = {
            chunk.chunk_id: str(chunk.metadata.get("visual_description") or "")
            for chunk in chunks
        }
        described_chunks = active_describer.describe_chunks(chunks)
        visual_chunks_described += sum(
            1
            for chunk in described_chunks
            if str(chunk.metadata.get("visual_description") or "")
            and str(chunk.metadata.get("visual_description") or "") != before.get(chunk.chunk_id, "")
        )
        visual_chunks_skipped += sum(
            1
            for chunk in described_chunks
            if chunk.metadata.get("visual_description_skipped")
        )
        updated_document = sync_visual_descriptions_to_document(document, described_chunks)
        if write and updated_document != document:
            _write_document(path, updated_document)
            papers_written += 1

    return VisualDescriptionBatchResult(
        papers_seen=len(paper_paths),
        papers_written=papers_written,
        visual_chunks_seen=visual_chunks_seen,
        visual_chunks_described=visual_chunks_described,
        visual_chunks_skipped=visual_chunks_skipped,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = describe_visual_artifacts(
        papers_dir=Path(args.papers_dir),
        image_root=Path(args.image_root) if args.image_root else Path(args.papers_dir),
        write=args.write,
    )
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend.research.rag.visual.describe_visual_artifacts",
        description="Describe figure/table images and persist visual_description into research_document.json.",
    )
    parser.add_argument("--papers-dir", required=True, help="Directory containing per-paper research_document.json files.")
    parser.add_argument("--image-root", help="Root used to resolve relative figure/table image refs.")
    parser.add_argument("--write", action="store_true", help="Write updated research_document.json files.")
    return parser


def _build_describer(*, image_root: Path) -> OpenAICompatibleVisualChunkDescriber:
    config = VisualChunkDescriptionConfig.from_env(image_root=image_root)
    config = config.__class__(
        enabled=True,
        base_url=config.base_url,
        model=config.model,
        api_key_env=config.api_key_env,
        timeout_seconds=config.timeout_seconds,
        max_tokens=config.max_tokens,
        image_root=config.image_root or image_root,
    )
    if not config.base_url:
        raise ValueError("visual description requires OPENAI_BASE_URL or NEWS_VISUAL_DESCRIPTION_BASE_URL")
    import os

    if not os.environ.get(config.api_key_env):
        raise ValueError(f"visual description requires {config.api_key_env}")
    return OpenAICompatibleVisualChunkDescriber(config)


def _read_document(path: Path) -> ResearchDocument:
    return ResearchDocument.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _write_document(path: Path, document: ResearchDocument) -> None:
    path.write_text(
        json.dumps(document.model_dump(mode="json", exclude_none=True), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
