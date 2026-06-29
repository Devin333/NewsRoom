from __future__ import annotations

import argparse
import json
import math
import hashlib
import os
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, Sequence

from business.research.document.models import PaperChunk
from business.research.ports.field_embedding_index import FieldEmbeddingHit
from business.research.ports.visual_chunk_index import VisualChunkHit
from business.research.rag.adapters.paper_field_text import FIELD_NAMES, extract_field_texts
from business.research.rag.evaluation.paper_evaluation_report import EvidenceRegressionReport
from business.research.rag.evaluation.paper_evidence_eval import (
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
        if args.page_visual:
            from business.research.rag.visual.page_visual_chunks import build_page_visual_chunks

            chunks.extend(build_page_visual_chunks(
                chunks,
                papers_dir=Path(args.papers_dir),
                render_pages=not args.no_render_page_visual,
            ))
        if args.vision_descriptions:
            chunks = _describe_visual_chunks(
                chunks,
                image_root=Path(args.image_root) if args.image_root else Path(args.papers_dir),
            )
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
        metadata["visual_descriptions_enabled"] = bool(args.vision_descriptions)
        metadata["visual_described_chunks"] = _visual_described_count(chunks)
        metadata["page_visual_enabled"] = bool(args.page_visual)
        metadata["page_visual_chunks"] = _page_visual_count(chunks)
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
            retrieval_policy=args.retrieval_policy,
            lightweight_reranker=args.lightweight_reranker,
        )
        retrieval = EvidenceRetrievalEvaluator(retriever).evaluate(pairs)
        policy = retriever.policy
        metadata["retrieval_policy"] = policy.name
        metadata["retrieval_policy_overfetch_multiplier"] = policy.overfetch_multiplier
        metadata["retrieval_policy_child_score_weights"] = policy.normalized_child_score_weights()
        metadata["retrieval_policy_visual_fusion_weights"] = {
            "text": policy.visual_fusion_text_weight,
            "visual": policy.visual_fusion_visual_weight,
        }
        metadata["visual_fusion_enabled"] = visual_store is not None
        metadata["visual_indexed_chunks"] = _visual_indexed_count(visual_store)
        metadata["lightweight_reranker_enabled"] = _lightweight_reranker_enabled(
            args.retrieval_policy,
            explicit=args.lightweight_reranker,
        )
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
        prog="python -m business.research.rag.cli.run_evidence_eval",
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
        "--page-visual",
        action="store_true",
        help="Add PDF page-level visual chunks to live retrieval/evaluation.",
    )
    parser.add_argument(
        "--no-render-page-visual",
        action="store_true",
        help="Do not render missing PDF page images when --page-visual is used.",
    )
    parser.add_argument(
        "--vision-descriptions",
        action="store_true",
        help="Use OPENAI_*-configured multimodal model to describe figure/table images before indexing.",
    )
    parser.add_argument(
        "--image-root",
        help="Root used to resolve relative figure image refs for --visual.",
    )
    parser.add_argument(
        "--retrieval-policy",
        default="",
        help=(
            "Named retrieval policy for --live-retrieval, for example "
            "paper_visual_rag_tuned or paper_blind_semantic_rag_v1."
        ),
    )
    parser.add_argument(
        "--lightweight-reranker",
        action="store_true",
        help="Enable deterministic structured field reranking for --live-retrieval.",
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
    retrieval_policy: str | None = None,
    lightweight_reranker: bool = False,
):
    from business.research.rag.retrieval.paper_retriever import ResearchRetriever, build_retrieval_policy
    from business.research.rag.retrieval.paper_claim_index import PaperClaimIndex

    chunk_store = _InMemoryChunkStore()
    chunk_store.ensure_collection()
    chunk_store.index_chunks(chunks)
    claim_index = PaperClaimIndex.from_chunks(chunks)

    field_index = _InMemoryFieldEmbeddingIndex()
    field_index.ensure_collection()
    field_index.index_chunks(chunks)

    visual_store = None
    if visual_enabled:
        visual_store = _InMemoryVisualStore(
            _DeterministicVisualEmbedding(),
            image_root=image_root,
        )
        visual_store.ensure_collection()
        visual_store.index_chunks(chunks)
    policy = build_retrieval_policy(retrieval_policy)
    field_reranker = None
    if _lightweight_reranker_enabled(retrieval_policy, explicit=lightweight_reranker):
        from business.research.rag.retrieval.paper_lightweight_reranker import LightweightLexicalReranker

        field_reranker = LightweightLexicalReranker()
    return ResearchRetriever(
        chunk_store,
        policy=policy,
        field_index=field_index,
        field_reranker=field_reranker,
        visual_store=visual_store,
        claim_index=claim_index,
    ), visual_store


def _lightweight_reranker_enabled(retrieval_policy: str | None, *, explicit: bool) -> bool:
    if explicit:
        return True
    from business.research.rag.retrieval.paper_retriever import retrieval_policy_enables_lightweight_reranker

    return retrieval_policy_enables_lightweight_reranker(retrieval_policy)


def _describe_visual_chunks(chunks: list[PaperChunk], *, image_root: Path) -> list[PaperChunk]:
    from business.research.application.visual_chunk_describer import (
        VisualChunkDescriptionConfig,
        OpenAICompatibleVisualChunkDescriber,
    )

    config = replace(VisualChunkDescriptionConfig.from_env(image_root=image_root), enabled=True)
    if not config.base_url:
        raise ValueError("--vision-descriptions requires OPENAI_BASE_URL or NEWS_VISUAL_DESCRIPTION_BASE_URL")
    if not os.environ.get(config.api_key_env):
        raise ValueError(f"--vision-descriptions requires {config.api_key_env}")
    describer = OpenAICompatibleVisualChunkDescriber(config)
    return describer.describe_chunks(chunks)


def _visual_indexed_count(visual_store) -> int:
    if visual_store is None:
        return 0
    return len(getattr(visual_store, "_vectors", {}))


def _visual_described_count(chunks: list[PaperChunk]) -> int:
    return sum(1 for chunk in chunks if chunk.metadata.get("visual_description"))


def _page_visual_count(chunks: list[PaperChunk]) -> int:
    return sum(1 for chunk in chunks if chunk.metadata.get("page_visual"))


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


class _InMemoryFieldEmbeddingIndex:
    def __init__(self) -> None:
        self._chunks: dict[str, PaperChunk] = {}
        self._vectors: dict[tuple[str, str], list[float]] = {}
        self._texts: dict[tuple[str, str], str] = {}
        self._payloads: dict[tuple[str, str], dict[str, Any]] = {}

    def ensure_collection(self) -> None:
        pass

    def index_chunks(self, chunks: list[PaperChunk]) -> None:
        for chunk in chunks:
            self._chunks[chunk.chunk_id] = chunk
            field_texts = extract_field_texts(chunk)
            for field_name, field_text in field_texts.non_empty().items():
                normalized = str(field_name).strip().casefold()
                if normalized not in FIELD_NAMES:
                    continue
                key = (chunk.chunk_id, normalized)
                self._texts[key] = field_text
                self._vectors[key] = _embed_text(field_text)
                self._payloads[key] = {
                    "paper_id": chunk.paper_id,
                    "chunk_id": chunk.chunk_id,
                    "field_name": normalized,
                    "field_text": field_text,
                    "field_text_sources": list(field_texts.sources_for(normalized)),
                    "chunk_type": chunk.chunk_type,
                    "section_title": chunk.section_title,
                    "section_role": list(chunk.section_role),
                    "section_index": chunk.section_index,
                    "has_formula": chunk.has_formula,
                    "has_figure": chunk.has_figure,
                    "has_table": chunk.has_table,
                    "figure_id": chunk.figure_id,
                    "table_id": chunk.metadata.get("table_id", ""),
                    "source_locator": chunk.metadata.get("source_locator", ""),
                    "caption_source_locator": chunk.metadata.get("caption_source_locator", ""),
                    "page": chunk.metadata.get("page"),
                    "pdf_rect": chunk.metadata.get("pdf_rect"),
                    "caption_pdf_rect": chunk.metadata.get("caption_pdf_rect"),
                }

    def delete_paper_chunks(self, paper_id: str) -> None:
        chunk_ids = [
            chunk_id
            for chunk_id, chunk in self._chunks.items()
            if chunk.paper_id == paper_id
        ]
        for chunk_id in chunk_ids:
            self._chunks.pop(chunk_id, None)
            for key in list(self._texts):
                if key[0] == chunk_id:
                    self._texts.pop(key, None)
                    self._vectors.pop(key, None)
                    self._payloads.pop(key, None)

    def search_field_vectors(
        self,
        paper_id: str,
        query_text: str,
        *,
        field_names: tuple[str, ...] | None = None,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[FieldEmbeddingHit]:
        query_vector = _embed_text(query_text)
        allowed_fields = set(_normalized_field_names(field_names))
        hits: list[FieldEmbeddingHit] = []
        for key, vector in self._vectors.items():
            chunk_id, field_name = key
            if allowed_fields and field_name not in allowed_fields:
                continue
            chunk = self._chunks.get(chunk_id)
            if chunk is None or chunk.paper_id != paper_id or not _matches_filters(chunk, filters or {}):
                continue
            score = _cosine_similarity(query_vector, vector)
            hits.append(FieldEmbeddingHit(
                chunk_id=chunk_id,
                field_name=field_name,
                score=score,
                field_text=self._texts[key],
                metadata=dict(self._payloads[key]),
            ))
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:limit]


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
        if key == "chunk_type" and value in set(chunk.metadata.get("source_evidence_types") or []):
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


def _normalized_field_names(field_names: tuple[str, ...] | None) -> tuple[str, ...]:
    if not field_names:
        return ()
    seen: set[str] = set()
    out: list[str] = []
    for field_name in field_names:
        normalized = str(field_name).strip().casefold()
        if normalized in FIELD_NAMES and normalized not in seen:
            out.append(normalized)
            seen.add(normalized)
    return tuple(out)


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
