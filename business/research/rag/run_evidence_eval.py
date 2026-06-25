from __future__ import annotations

import argparse
import json
import math
import hashlib
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

from business.research.document.models import PaperChunk
from business.research.ports.visual_chunk_index import VisualChunkHit
from business.research.rag.evaluation_report import EvidenceRegressionReport
from business.research.rag.evidence_eval import (
    EvidenceGoldenSetBuilder,
    EvidenceRetrievalEvaluator,
    load_evidence_golden_set,
    save_evidence_golden_set,
)


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    pairs = []
    chunks = []
    visual_store = None
    if args.papers_dir:
        chunks = _load_chunks_from_papers_dir(Path(args.papers_dir))
    if args.build_golden_set:
        if not chunks:
            raise ValueError("--build-golden-set requires --papers-dir")
        pairs = EvidenceGoldenSetBuilder(
            max_pairs_per_type=args.max_pairs_per_type,
            include_negative=not args.no_negative,
        ).build(chunks, domain=args.domain)
        if args.golden_set:
            save_evidence_golden_set(pairs, args.golden_set)
    elif args.golden_set:
        pairs = load_evidence_golden_set(args.golden_set)
    if not pairs:
        raise ValueError("--golden-set is required unless --papers-dir --build-golden-set produces pairs")

    metadata = {
        "golden_set": str(Path(args.golden_set)) if args.golden_set else "",
        "total_pairs": len(pairs),
        "mode": "live_retrieval" if args.live_retrieval else "summary",
    }
    if args.papers_dir:
        metadata["papers_dir"] = str(Path(args.papers_dir))
        metadata["chunks_total"] = len(chunks)
    qa_type_counts = Counter(pair.qa_type for pair in pairs)
    behavior_counts = Counter(pair.expected_behavior for pair in pairs)
    metadata["qa_type_counts"] = dict(sorted(qa_type_counts.items()))
    metadata["expected_behavior_counts"] = dict(sorted(behavior_counts.items()))

    thresholds = _parse_thresholds(args.threshold)
    retrieval = None
    if args.live_retrieval:
        if not chunks:
            raise ValueError("--live-retrieval requires --papers-dir with parsed research_document.json files")
        retriever, visual_store = _build_live_retriever(
            chunks,
            visual_enabled=args.visual,
            image_root=Path(args.image_root) if args.image_root else None,
        )
        retrieval = EvidenceRetrievalEvaluator(retriever).evaluate(pairs)
        metadata["visual_fusion_enabled"] = visual_store is not None
        metadata["visual_indexed_chunks"] = _visual_indexed_count(visual_store)
    report = EvidenceRegressionReport(
        retrieval=retrieval,
        metadata=metadata,
        thresholds=thresholds,
    )
    report.write(args.output_dir)
    print(report.to_markdown(), end="")
    return 0 if report.passed() else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m business.research.rag.run_evidence_eval",
        description="Write a paper RAG evidence benchmark summary/report from a golden set.",
    )
    parser.add_argument("--golden-set", help="Path to EvidenceQAPair JSON golden set.")
    parser.add_argument(
        "--output-dir",
        default=".newsroom/eval/evidence",
        help="Directory for evidence_regression_report.{json,md}.",
    )
    parser.add_argument(
        "--papers-dir",
        help="Directory containing per-paper research_document.json artifacts.",
    )
    parser.add_argument(
        "--build-golden-set",
        action="store_true",
        help="Build deterministic evidence QA pairs from --papers-dir before evaluating.",
    )
    parser.add_argument(
        "--max-pairs-per-type",
        type=int,
        default=20,
        help="Maximum deterministic QA pairs per type when --build-golden-set is used.",
    )
    parser.add_argument(
        "--no-negative",
        action="store_true",
        help="Skip negative QA pairs when --build-golden-set is used.",
    )
    parser.add_argument(
        "--domain",
        default="",
        help="Domain label written into generated QA pairs.",
    )
    parser.add_argument(
        "--live-retrieval",
        action="store_true",
        help="Index parsed paper chunks in memory and run EvidenceRetrievalEvaluator.",
    )
    parser.add_argument(
        "--visual",
        action="store_true",
        help="Enable in-memory visual indexing for figure chunks during --live-retrieval.",
    )
    parser.add_argument(
        "--image-root",
        help="Root used to resolve relative figure image refs for --visual.",
    )
    parser.add_argument(
        "--threshold",
        action="append",
        default=[],
        metavar="METRIC=VALUE",
        help="Optional threshold, for example retrieval.evidence_coverage=0.8.",
    )
    return parser


def _load_chunks_from_papers_dir(papers_dir: Path):
    from business.research.document.chunker import PaperDocumentChunker
    from business.research.domain.document import ResearchDocument

    chunker = PaperDocumentChunker()
    chunks = []
    for path in sorted(papers_dir.glob("*/research_document.json")):
        document = ResearchDocument.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )
        parse_source = str(document.metadata.get("parse_source") or "nougat")
        chunks.extend(chunker.chunk(document, parse_source))  # type: ignore[arg-type]
    return chunks


def _build_live_retriever(
    chunks,
    *,
    visual_enabled: bool,
    image_root: Path | None,
):
    from business.research.rag.retriever import ResearchRetriever

    chunk_store = _InMemoryChunkStore()
    chunk_store.ensure_collection()
    chunk_store.index_chunks(chunks)

    visual_store = None
    if visual_enabled:
        visual_store = _InMemoryVisualStore(
            _DeterministicVisualEmbedding(),
            image_root=image_root,
        )
        visual_store.ensure_collection()
        visual_store.index_chunks(chunks)
    return ResearchRetriever(chunk_store, visual_store=visual_store), visual_store


def _visual_indexed_count(visual_store) -> int:
    if visual_store is None:
        return 0
    return len(getattr(visual_store, "_vectors", {}))


class _InMemoryChunkStore:
    def __init__(self) -> None:
        self._chunks: dict[str, PaperChunk] = {}

    def ensure_collection(self) -> None:
        pass

    def index_chunks(self, chunks: list[PaperChunk]) -> None:
        self._chunks.update({chunk.chunk_id: chunk for chunk in chunks})

    def search_chunks(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
        score_threshold: float | None = None,
    ) -> list[PaperChunk]:
        return [
            chunk
            for chunk, score in self.search_with_scores(
                paper_id,
                query_text,
                filters=filters,
                limit=limit,
            )
            if score_threshold is None or score >= score_threshold
        ]

    def search_with_scores(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 30,
    ) -> list[tuple[PaperChunk, float]]:
        query_vector = _embed_text(query_text)
        scored = []
        for chunk in self._chunks.values():
            if chunk.paper_id != paper_id or not _matches_filters(chunk, filters or {}):
                continue
            scored.append((chunk, _cosine_similarity(query_vector, _embed_text(chunk.content))))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:limit]

    def get_chunk(self, chunk_id: str) -> PaperChunk | None:
        return self._chunks.get(chunk_id)

    def get_parent_chunk(self, chunk: PaperChunk) -> PaperChunk | None:
        return self.get_chunk(chunk.parent_chunk_id) if chunk.parent_chunk_id else None


class _InMemoryVisualStore:
    def __init__(self, visual_model, *, image_root: Path | None) -> None:
        self._visual_model = visual_model
        self._image_root = image_root
        self._chunks: dict[str, PaperChunk] = {}
        self._vectors: dict[str, list[float]] = {}

    def ensure_collection(self) -> None:
        pass

    def index_chunks(self, chunks: list[PaperChunk]) -> None:
        for chunk in chunks:
            if chunk.chunk_type != "figure" or not chunk.metadata.get("image_ref"):
                continue
            image_ref = str(chunk.metadata.get("image_ref") or "")
            image_path = _resolve_image_path(
                image_ref,
                paper_id=chunk.paper_id,
                image_root=self._image_root,
            )
            if not image_path.exists():
                continue
            self._chunks[chunk.chunk_id] = chunk
            self._vectors[chunk.chunk_id] = self._visual_model.embed_image(str(image_path))

    def delete_paper_chunks(self, paper_id: str) -> None:
        ids = [
            chunk_id
            for chunk_id, chunk in self._chunks.items()
            if chunk.paper_id == paper_id
        ]
        for chunk_id in ids:
            self._chunks.pop(chunk_id, None)
            self._vectors.pop(chunk_id, None)

    def search_visual_chunks(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[VisualChunkHit]:
        query_vector = self._visual_model.embed_text(query_text)
        hits = []
        for chunk_id, chunk in self._chunks.items():
            if chunk.paper_id != paper_id or not _matches_filters(chunk, filters or {}):
                continue
            hits.append(VisualChunkHit(
                chunk_id=chunk_id,
                score=_cosine_similarity(query_vector, self._vectors[chunk_id]),
                metadata={
                    "chunk_id": chunk_id,
                    "paper_id": chunk.paper_id,
                    "chunk_type": chunk.chunk_type,
                    "image_ref": chunk.metadata.get("image_ref", ""),
                    "visual_indexed": True,
                },
            ))
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:limit]


def _matches_filters(chunk: PaperChunk, filters: dict[str, Any]) -> bool:
    for key, value in filters.items():
        if getattr(chunk, key, None) == value:
            continue
        if chunk.metadata.get(key) == value:
            continue
        return False
    return True


def _resolve_image_path(image_ref: str, *, paper_id: str, image_root: Path | None) -> Path:
    normalized = image_ref.replace("\\", "/")
    path = Path(normalized)
    if path.is_absolute():
        return path
    candidates = []
    if image_root is not None:
        candidates.extend([image_root / path, image_root / paper_id / path])
        if path.parts and path.parts[0] == ".newsroom":
            candidates.append(Path.cwd() / path)
        newsroom_index = normalized.find(".newsroom/")
        if newsroom_index > 0:
            candidates.append(Path.cwd() / normalized[newsroom_index:])
    candidates.append(Path.cwd() / path)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


class _DeterministicVisualEmbedding:
    dimension = 64

    def embed_text(self, text: str) -> list[float]:
        return _embed_text(text, dimension=self.dimension)

    def embed_image(self, image_path: str) -> list[float]:
        return _embed_text(Path(image_path).stem.replace("_", " "), dimension=self.dimension)

    def embed_images(self, image_paths: list[str]) -> list[list[float]]:
        return [self.embed_image(path) for path in image_paths]


def _embed_text(text: str, *, dimension: int = 64) -> list[float]:
    vector = [0.0] * dimension
    tokens = [
        token
        for token in "".join(
            char.lower() if char.isalnum() else " "
            for char in text
        ).split()
        if token
    ]
    if not tokens:
        return vector
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimension
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def _parse_thresholds(values: list[str]) -> dict[str, float]:
    thresholds: dict[str, float] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"threshold must use METRIC=VALUE form: {value!r}")
        key, raw = value.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError("threshold metric is required")
        thresholds[key] = float(raw)
    return thresholds


if __name__ == "__main__":
    raise SystemExit(main())
