from __future__ import annotations

import json
import hashlib
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

from framework.rag.evaluation import (
    RetrievalMetricCase,
    evidence_coverage as kernel_evidence_coverage,
    hit_at_k as kernel_hit_at_k,
    ndcg_at_k as kernel_ndcg_at_k,
    reciprocal_rank as kernel_reciprocal_rank,
    source_locator_coverage as kernel_source_locator_coverage,
)
from framework.rag.retrieval import dedupe_by_key

from business.research.document.citation_spans import resolve_citation_span
from business.research.document.models import PaperChunk
from business.research.rag.adapters.paper_chunk_adapter import paper_chunk_to_rag_evidence
from business.research.rag.retrieval.paper_claim_index import extract_claim_records
from business.research.rag.retrieval.contracts import RetrievalRequest
from business.research.rag.retrieval.paper_retriever import ResearchRetriever

EvidenceBehavior = Literal["answer", "abstain"]
QuestionProfile = Literal["template", "blind_detemplated", "blind_semantic"]


_DEFAULT_KS = (1, 3, 5, 10)
_ANSWER_BEHAVIOR: EvidenceBehavior = "answer"
_ABSTAIN_BEHAVIOR: EvidenceBehavior = "abstain"
_DEFAULT_MAX_PAIRS_PER_TYPE = 20


@dataclass
class EvidenceQAPair:
    """A benchmark question with one or more required evidence chunks."""

    question: str
    paper_id: str
    qa_type: str
    gold_chunk_ids: list[str] = field(default_factory=list)
    equivalent_gold_chunk_ids: list[str] = field(default_factory=list)
    supporting_evidence_group_id: str = ""
    required_primary_evidence_ids: list[str] = field(default_factory=list)
    acceptable_support_evidence_ids: list[str] = field(default_factory=list)
    gold_claim_ids: list[str] = field(default_factory=list)
    supporting_evidence_group: dict[str, Any] = field(default_factory=dict)
    required_evidence_types: list[str] = field(default_factory=list)
    gold_source_locators: list[str] = field(default_factory=list)
    gold_citation_spans: list[dict[str, Any]] = field(default_factory=list)
    gold_image_refs: list[str] = field(default_factory=list)
    answer_facts: list[str] = field(default_factory=list)
    expected_behavior: EvidenceBehavior = _ANSWER_BEHAVIOR
    difficulty: str = ""
    domain: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.question = _require_text(self.question, "question")
        self.paper_id = _require_text(self.paper_id, "paper_id")
        self.qa_type = _require_text(self.qa_type, "qa_type")
        self.expected_behavior = _coerce_behavior(self.expected_behavior)
        self.gold_chunk_ids = _unique_texts(self.gold_chunk_ids)
        self.equivalent_gold_chunk_ids = _unique_texts(self.equivalent_gold_chunk_ids or self.gold_chunk_ids)
        self.supporting_evidence_group_id = str(self.supporting_evidence_group_id or "").strip()
        self.required_primary_evidence_ids = _unique_texts(self.required_primary_evidence_ids or self.gold_chunk_ids)
        self.acceptable_support_evidence_ids = _unique_texts(self.acceptable_support_evidence_ids)
        self.gold_claim_ids = _unique_texts(self.gold_claim_ids)
        self.supporting_evidence_group = dict(self.supporting_evidence_group or {})
        self.required_evidence_types = _unique_texts(self.required_evidence_types)
        self.gold_source_locators = _unique_texts(self.gold_source_locators)
        self.gold_citation_spans = _normalize_citation_spans(self.gold_citation_spans)
        self.gold_image_refs = _unique_texts(self.gold_image_refs)
        self.answer_facts = _unique_texts(self.answer_facts)
        if self.expected_behavior == _ANSWER_BEHAVIOR and not self.gold_chunk_ids:
            raise ValueError("answer evidence QA requires at least one gold chunk id")

    @classmethod
    def from_source_chunk(
        cls,
        *,
        question: str,
        chunk: PaperChunk,
        qa_type: str | None = None,
        required_evidence_types: list[str] | None = None,
        answer_facts: list[str] | None = None,
        difficulty: str = "",
        domain: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> "EvidenceQAPair":
        source_locator = str(chunk.metadata.get("source_locator") or "")
        image_ref = str(chunk.metadata.get("image_ref") or "")
        return cls(
            question=question,
            paper_id=chunk.paper_id,
            qa_type=qa_type or _qa_type_for_chunk(chunk),
            gold_chunk_ids=[chunk.chunk_id],
            required_evidence_types=required_evidence_types or [_evidence_type_for_chunk(chunk)],
            gold_source_locators=[source_locator] if source_locator else [],
            gold_image_refs=[image_ref] if image_ref else [],
            answer_facts=answer_facts or [],
            expected_behavior=_ANSWER_BEHAVIOR,
            difficulty=difficulty,
            domain=domain,
            metadata=metadata or {},
        )

    @classmethod
    def negative(
        cls,
        *,
        question: str,
        paper_id: str,
        qa_type: str = "negative_qa",
        difficulty: str = "",
        domain: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> "EvidenceQAPair":
        return cls(
            question=question,
            paper_id=paper_id,
            qa_type=qa_type,
            expected_behavior=_ABSTAIN_BEHAVIOR,
            difficulty=difficulty,
            domain=domain,
            metadata=metadata or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "paper_id": self.paper_id,
            "qa_type": self.qa_type,
            "gold_chunk_ids": list(self.gold_chunk_ids),
            "equivalent_gold_chunk_ids": list(self.equivalent_gold_chunk_ids),
            "supporting_evidence_group_id": self.supporting_evidence_group_id,
            "required_primary_evidence_ids": list(self.required_primary_evidence_ids),
            "acceptable_support_evidence_ids": list(self.acceptable_support_evidence_ids),
            "gold_claim_ids": list(self.gold_claim_ids),
            "supporting_evidence_group": dict(self.supporting_evidence_group),
            "required_evidence_types": list(self.required_evidence_types),
            "gold_source_locators": list(self.gold_source_locators),
            "gold_citation_spans": [dict(span) for span in self.gold_citation_spans],
            "gold_image_refs": list(self.gold_image_refs),
            "answer_facts": list(self.answer_facts),
            "expected_behavior": self.expected_behavior,
            "difficulty": self.difficulty,
            "domain": self.domain,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceQAPair":
        gold_chunk_ids = list(data.get("gold_chunk_ids") or [])
        legacy_source_chunk_id = str(data.get("source_chunk_id") or "").strip()
        if not gold_chunk_ids and legacy_source_chunk_id:
            gold_chunk_ids = [legacy_source_chunk_id]
        return cls(
            question=str(data["question"]),
            paper_id=str(data["paper_id"]),
            qa_type=str(data.get("qa_type") or "legacy_qa"),
            gold_chunk_ids=gold_chunk_ids,
            equivalent_gold_chunk_ids=list(data.get("equivalent_gold_chunk_ids") or []),
            supporting_evidence_group_id=str(data.get("supporting_evidence_group_id") or ""),
            required_primary_evidence_ids=list(data.get("required_primary_evidence_ids") or []),
            acceptable_support_evidence_ids=list(data.get("acceptable_support_evidence_ids") or []),
            gold_claim_ids=list(data.get("gold_claim_ids") or []),
            supporting_evidence_group=dict(data.get("supporting_evidence_group") or {}),
            required_evidence_types=list(data.get("required_evidence_types") or []),
            gold_source_locators=list(data.get("gold_source_locators") or []),
            gold_citation_spans=list(data.get("gold_citation_spans") or []),
            gold_image_refs=list(data.get("gold_image_refs") or []),
            answer_facts=list(data.get("answer_facts") or []),
            expected_behavior=_coerce_behavior(data.get("expected_behavior", _ANSWER_BEHAVIOR)),
            difficulty=str(data.get("difficulty") or ""),
            domain=str(data.get("domain") or ""),
            metadata={
                **({"source_chunk_id": legacy_source_chunk_id} if legacy_source_chunk_id else {}),
                **dict(data.get("metadata") or {}),
            },
        )


@dataclass(frozen=True)
class EvidenceSampleResult:
    pair: EvidenceQAPair
    ranked_chunk_ids: list[str]
    ranked_match_chunk_ids: list[list[str]]
    ranked_evidence_types: list[str]
    ranked_evidence_type_candidates: list[list[str]]
    ranked_source_locators: list[str]
    ranked_source_locator_candidates: list[list[str]]
    ranked_image_refs: list[str]
    ranked_image_ref_candidates: list[list[str]]
    ranked_score_breakdowns: list[dict[str, float]] = field(default_factory=list)
    first_rank: int = 0
    equivalent_first_rank: int = 0
    coverage_by_k: dict[int, float] = field(default_factory=dict)
    equivalent_coverage_by_k: dict[int, float] = field(default_factory=dict)
    type_coverage_by_k: dict[int, float] = field(default_factory=dict)
    source_locator_coverage_by_k: dict[int, float] = field(default_factory=dict)
    image_recall_by_k: dict[int, float] = field(default_factory=dict)
    visual_evidence_coverage_by_k: dict[int, float] = field(default_factory=dict)
    citation_accuracy_by_k: dict[int, float | None] = field(default_factory=dict)
    overlap_citation_accuracy_by_k: dict[int, float | None] = field(default_factory=dict)
    over_retrieval_by_k: dict[int, int] = field(default_factory=dict)
    retrieval_intent: str = ""
    recall_routes: tuple[str, ...] = ()
    retrieval_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_answerable(self) -> bool:
        return self.pair.expected_behavior == _ANSWER_BEHAVIOR


@dataclass
class EvidenceEvalResult:
    total: int
    answerable_total: int
    abstain_total: int
    ks: tuple[int, ...] = _DEFAULT_KS
    hit_at: dict[int, int] = field(default_factory=dict)
    equivalent_hit_at: dict[int, int] = field(default_factory=dict)
    evidence_coverage_at: dict[int, list[float]] = field(default_factory=dict)
    equivalent_evidence_coverage_at: dict[int, list[float]] = field(default_factory=dict)
    required_type_coverage_at: dict[int, list[float]] = field(default_factory=dict)
    source_locator_coverage_at: dict[int, list[float]] = field(default_factory=dict)
    image_recall_at: dict[int, list[float]] = field(default_factory=dict)
    visual_evidence_coverage_at: dict[int, list[float]] = field(default_factory=dict)
    citation_accuracy_at: dict[int, list[float]] = field(default_factory=dict)
    overlap_citation_accuracy_at: dict[int, list[float]] = field(default_factory=dict)
    over_retrieval_at: dict[int, list[int]] = field(default_factory=dict)
    reciprocal_ranks: list[float] = field(default_factory=list)
    equivalent_reciprocal_ranks: list[float] = field(default_factory=list)
    ndcg_at: dict[int, list[float]] = field(default_factory=dict)
    intent_distribution: dict[str, int] = field(default_factory=dict)
    route_distribution: dict[str, int] = field(default_factory=dict)
    intent_confusion: dict[str, dict[str, int]] = field(default_factory=dict)
    by_qa_type: dict[str, "EvidenceEvalResult"] = field(default_factory=dict)
    samples: list[EvidenceSampleResult] = field(default_factory=list)

    def hit_rate(self, k: int) -> float:
        return self.hit_at.get(k, 0) / self.answerable_total if self.answerable_total else 0.0

    def evidence_coverage(self, k: int) -> float:
        return _average(self.evidence_coverage_at.get(k, []))

    def equivalent_hit_rate(self, k: int) -> float:
        return self.equivalent_hit_at.get(k, 0) / self.answerable_total if self.answerable_total else 0.0

    def equivalent_evidence_coverage(self, k: int) -> float:
        return _average(self.equivalent_evidence_coverage_at.get(k, []))

    def required_type_coverage(self, k: int) -> float:
        return _average(self.required_type_coverage_at.get(k, []))

    def source_locator_coverage(self, k: int) -> float:
        return _average(self.source_locator_coverage_at.get(k, []))

    def image_recall(self, k: int) -> float:
        return _average(self.image_recall_at.get(k, []))

    def visual_evidence_coverage(self, k: int) -> float:
        return _average(self.visual_evidence_coverage_at.get(k, []))

    def over_retrieval_rate(self, k: int) -> float:
        values = self.over_retrieval_at.get(k, [])
        return sum(1 for value in values if value > 0) / len(values) if values else 0.0

    def citation_accuracy(self, k: int) -> float:
        return _average(self.citation_accuracy_at.get(k, []))

    def overlap_citation_accuracy(self, k: int) -> float:
        return _average(self.overlap_citation_accuracy_at.get(k, []))

    def mrr(self) -> float:
        return _average(self.reciprocal_ranks)

    def equivalent_mrr(self) -> float:
        return _average(self.equivalent_reciprocal_ranks)

    def ndcg(self, k: int) -> float:
        return _average(self.ndcg_at.get(k, []))

    def report(self, ks: tuple[int, ...] | None = None) -> str:
        report_ks = ks or self.ks
        lines = [
            f"=== Evidence Retrieval Eval (n={self.total}, answerable={self.answerable_total}, abstain={self.abstain_total}) ==="
        ]
        for k in report_ks:
            lines.append(
                f"  Hit@{k:<2} = {self.hit_rate(k):6.1%}    "
                f"EquivalentHit@{k:<2} = {self.equivalent_hit_rate(k):6.1%}    "
                f"EvidenceCoverage@{k:<2} = {self.evidence_coverage(k):.3f}    "
                f"EquivalentCoverage@{k:<2} = {self.equivalent_evidence_coverage(k):.3f}    "
                f"TypeCoverage@{k:<2} = {self.required_type_coverage(k):.3f}    "
                f"SourceLocatorCoverage@{k:<2} = {self.source_locator_coverage(k):.3f}    "
                f"ImageRecall@{k:<2} = {self.image_recall(k):.3f}    "
                f"CitationAccuracy@{k:<2} = {self.citation_accuracy(k):.3f}"
            )
        lines.append(f"  MRR     = {self.mrr():.3f}")
        lines.append(f"  EquivalentMRR = {self.equivalent_mrr():.3f}")
        if self.by_qa_type:
            lines.append("  -- by qa_type --")
            for qa_type in sorted(self.by_qa_type):
                sub = self.by_qa_type[qa_type]
                summary_k = 5 if 5 in sub.ks else max(sub.ks)
                lines.append(
                    f"     {qa_type:<18} n={sub.total:<3} "
                    f"Hit@{summary_k}={sub.hit_rate(summary_k):6.1%} "
                    f"EvidenceCoverage@{summary_k}={sub.evidence_coverage(summary_k):.3f}"
                )
        return "\n".join(lines)


class EvidenceRetrievalEvaluator:
    """Evaluates retrieval against typed, multi-evidence paper QA pairs."""

    def __init__(self, retriever: ResearchRetriever) -> None:
        self._retriever = retriever

    def evaluate(
        self,
        pairs: list[EvidenceQAPair],
        ks: tuple[int, ...] = _DEFAULT_KS,
    ) -> EvidenceEvalResult:
        max_k = max(ks)
        samples = [self._evaluate_pair(pair, ks=ks, max_k=max_k) for pair in pairs]
        result = _aggregate_samples(samples, ks=ks)
        by_type: dict[str, list[EvidenceSampleResult]] = {}
        for sample in samples:
            by_type.setdefault(sample.pair.qa_type, []).append(sample)
        result.by_qa_type = {
            qa_type: _aggregate_samples(type_samples, ks=ks)
            for qa_type, type_samples in by_type.items()
        }
        return result

    def _evaluate_pair(
        self,
        pair: EvidenceQAPair,
        *,
        ks: tuple[int, ...],
        max_k: int,
    ) -> EvidenceSampleResult:
        if pair.expected_behavior == _ABSTAIN_BEHAVIOR:
            return EvidenceSampleResult(
                pair=pair,
                ranked_chunk_ids=[],
                ranked_match_chunk_ids=[],
                ranked_evidence_types=[],
                ranked_evidence_type_candidates=[],
                ranked_source_locators=[],
                ranked_source_locator_candidates=[],
                ranked_image_refs=[],
                ranked_image_ref_candidates=[],
                ranked_score_breakdowns=[],
                first_rank=0,
                equivalent_first_rank=0,
                coverage_by_k={k: 0.0 for k in ks},
                equivalent_coverage_by_k={k: 0.0 for k in ks},
                type_coverage_by_k={k: 0.0 for k in ks},
                source_locator_coverage_by_k={k: 0.0 for k in ks},
                image_recall_by_k={k: 0.0 for k in ks},
                visual_evidence_coverage_by_k={k: 0.0 for k in ks},
                citation_accuracy_by_k={k: None for k in ks},
                overlap_citation_accuracy_by_k={k: None for k in ks},
                over_retrieval_by_k={k: 0 for k in ks},
                retrieval_intent="abstain",
                recall_routes=(),
                retrieval_metadata={},
            )

        retrieved = self._retriever.retrieve(RetrievalRequest(
            paper_id=pair.paper_id,
            question=pair.question,
            limit=max_k,
        ))
        ranked_chunks = _ranked_unique_chunks([
            *retrieved.child_chunks,
            *retrieved.ref_chunks,
            *retrieved.parent_chunks,
        ])
        ranked_ids = [chunk.chunk_id for chunk in ranked_chunks]
        ranked_match_ids = [_chunk_match_ids(chunk) for chunk in ranked_chunks]
        ranked_types = [_evidence_type_for_chunk(chunk) for chunk in ranked_chunks]
        ranked_type_candidates = [_evidence_type_candidates_for_chunk(chunk) for chunk in ranked_chunks]
        ranked_locators = [_source_locator_for_chunk(chunk) for chunk in ranked_chunks]
        ranked_locator_candidates = [_source_locator_candidates_for_chunk(chunk) for chunk in ranked_chunks]
        ranked_images = [_image_ref_for_chunk(chunk) for chunk in ranked_chunks]
        ranked_image_candidates = [_image_ref_candidates_for_chunk(chunk) for chunk in ranked_chunks]
        ranked_score_breakdowns = [_score_breakdown_for_chunk(chunk) for chunk in ranked_chunks]
        retrieval_metadata = dict(retrieved.metadata)
        first_rank = _first_gold_rank(ranked_match_ids, pair.gold_chunk_ids)
        equivalent_gold_ids = pair.equivalent_gold_chunk_ids or pair.gold_chunk_ids
        equivalent_first_rank = _first_gold_rank(ranked_match_ids, equivalent_gold_ids)
        return EvidenceSampleResult(
            pair=pair,
            ranked_chunk_ids=ranked_ids,
            ranked_match_chunk_ids=ranked_match_ids,
            ranked_evidence_types=ranked_types,
            ranked_evidence_type_candidates=ranked_type_candidates,
            ranked_source_locators=ranked_locators,
            ranked_source_locator_candidates=ranked_locator_candidates,
            ranked_image_refs=ranked_images,
            ranked_image_ref_candidates=ranked_image_candidates,
            ranked_score_breakdowns=ranked_score_breakdowns,
            first_rank=first_rank,
            equivalent_first_rank=equivalent_first_rank,
            coverage_by_k={
                k: _candidate_coverage(ranked_match_ids[:k], pair.gold_chunk_ids)
                for k in ks
            },
            equivalent_coverage_by_k={
                k: _candidate_coverage(ranked_match_ids[:k], equivalent_gold_ids)
                for k in ks
            },
            type_coverage_by_k={
                k: _candidate_coverage(ranked_type_candidates[:k], pair.required_evidence_types)
                for k in ks
            },
            source_locator_coverage_by_k={
                k: _candidate_locator_coverage(ranked_locator_candidates[:k], pair.gold_source_locators)
                for k in ks
            },
            image_recall_by_k={
                k: _candidate_coverage(ranked_image_candidates[:k], pair.gold_image_refs)
                for k in ks
            },
            visual_evidence_coverage_by_k={
                k: _visual_evidence_coverage(ranked_chunks[:k], pair.gold_image_refs)
                for k in ks
            },
            citation_accuracy_by_k={
                k: _citation_accuracy(ranked_chunks[:k], pair.gold_citation_spans)
                for k in ks
            },
            overlap_citation_accuracy_by_k={
                k: _citation_accuracy(
                    ranked_chunks[:k],
                    pair.gold_citation_spans,
                    span_kind="overlap",
                )
                for k in ks
            },
            over_retrieval_by_k={
                k: _candidate_over_retrieval_count(ranked_match_ids[:k], pair.gold_chunk_ids)
                for k in ks
            },
            retrieval_intent=str(retrieved.intent),
            recall_routes=tuple(str(route) for route in retrieval_metadata.get("recall_routes") or ()),
            retrieval_metadata=retrieval_metadata,
        )


class EvidenceGoldenSetBuilder:
    """Builds typed evidence QA pairs from parsed paper chunks."""

    def __init__(
        self,
        *,
        max_pairs_per_type: int = _DEFAULT_MAX_PAIRS_PER_TYPE,
        include_negative: bool = True,
        question_profile: QuestionProfile = "template",
    ) -> None:
        self._max_pairs_per_type = max(1, int(max_pairs_per_type))
        self._include_negative = include_negative
        self._question_profile = _normalize_question_profile(question_profile)

    def build(self, chunks: list[PaperChunk], *, domain: str = "") -> list[EvidenceQAPair]:
        chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
        pairs: list[EvidenceQAPair] = []
        pairs.extend(self._build_type(chunks, "formula_qa", domain=domain))
        pairs.extend(self._build_formula_explanation_pairs(chunks, domain=domain, chunks_by_id=chunks_by_id))
        pairs.extend(self._build_type(chunks, "table_qa", domain=domain, chunks_by_id=chunks_by_id))
        pairs.extend(self._build_experiment_result_pairs(chunks, domain=domain, chunks_by_id=chunks_by_id))
        pairs.extend(self._build_type(chunks, "figure_qa", domain=domain, chunks_by_id=chunks_by_id))
        pairs.extend(self._build_type(chunks, "citation_qa", domain=domain))
        if self._include_negative:
            paper_ids = sorted({chunk.paper_id for chunk in chunks})
            for paper_id in paper_ids:
                pairs.append(EvidenceQAPair.negative(
                    question="Does this paper discuss an unrelated future model not present in the text?",
                    paper_id=paper_id,
                    difficulty="easy",
                    domain=domain,
                    metadata={"builder": "deterministic_template"},
                ))
        profiled = _apply_question_profile(pairs, self._question_profile, chunks_by_id=chunks_by_id)
        return _attach_evidence_groups(profiled, chunks_by_id=chunks_by_id)

    def _build_type(
        self,
        chunks: list[PaperChunk],
        qa_type: str,
        *,
        domain: str,
        chunks_by_id: dict[str, PaperChunk] | None = None,
    ) -> list[EvidenceQAPair]:
        out: list[EvidenceQAPair] = []
        for chunk in chunks:
            if _qa_type_for_chunk(chunk) != qa_type:
                continue
            pair = _template_pair_for_chunk(chunk, qa_type, domain=domain, chunks_by_id=chunks_by_id or {})
            if pair is not None:
                out.append(pair)
        return _balanced_by_paper(out, self._max_pairs_per_type)

    def _build_experiment_result_pairs(
        self,
        chunks: list[PaperChunk],
        *,
        domain: str,
        chunks_by_id: dict[str, PaperChunk],
    ) -> list[EvidenceQAPair]:
        out: list[EvidenceQAPair] = []
        for chunk in chunks:
            if _evidence_type_for_chunk(chunk) != "table":
                continue
            pair = _experiment_result_pair(chunk, domain=domain, chunks_by_id=chunks_by_id)
            if pair is not None:
                out.append(pair)
        return _balanced_by_paper(out, self._max_pairs_per_type)

    def _build_formula_explanation_pairs(
        self,
        chunks: list[PaperChunk],
        *,
        domain: str,
        chunks_by_id: dict[str, PaperChunk],
    ) -> list[EvidenceQAPair]:
        out: list[EvidenceQAPair] = []
        for chunk in chunks:
            if _evidence_type_for_chunk(chunk) != "formula":
                continue
            pair = _formula_explanation_pair(chunk, domain=domain, chunks_by_id=chunks_by_id)
            if pair is not None:
                out.append(pair)
        return _balanced_by_paper(out, self._max_pairs_per_type)


def save_evidence_golden_set(pairs: list[EvidenceQAPair], path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps([pair.to_dict() for pair in pairs], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_evidence_golden_set(path: str | Path) -> list[EvidenceQAPair]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [EvidenceQAPair.from_dict(item) for item in data]


def build_evidence_pairs_from_chunks(
    chunks: list[PaperChunk],
    *,
    questions_by_chunk_id: dict[str, list[str]],
    domain: str = "",
) -> list[EvidenceQAPair]:
    """Build deterministic evidence QA pairs from externally supplied questions."""
    pairs: list[EvidenceQAPair] = []
    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    for chunk_id, questions in questions_by_chunk_id.items():
        chunk = chunks_by_id.get(chunk_id)
        if chunk is None:
            continue
        for question in questions:
            pairs.append(EvidenceQAPair.from_source_chunk(
                question=question,
                chunk=chunk,
                domain=domain,
            ))
    return _attach_evidence_groups(pairs, chunks_by_id=chunks_by_id)


def _normalize_question_profile(profile: str) -> QuestionProfile:
    normalized = str(profile or "template").strip().casefold()
    if normalized in {"", "template"}:
        return "template"
    if normalized in {"blind", "blind_detemplated", "detemplated"}:
        return "blind_detemplated"
    if normalized in {"blind_semantic", "semantic", "semantic_blind"}:
        return "blind_semantic"
    raise ValueError("question_profile must be 'template', 'blind_detemplated', or 'blind_semantic'")


def _apply_question_profile(
    pairs: list[EvidenceQAPair],
    profile: QuestionProfile,
    *,
    chunks_by_id: dict[str, PaperChunk],
) -> list[EvidenceQAPair]:
    if profile == "template":
        return pairs
    if profile == "blind_detemplated":
        return [_detemplated_pair(pair, chunks_by_id=chunks_by_id) for pair in pairs]
    return [_blind_semantic_pair(pair, chunks_by_id=chunks_by_id) for pair in pairs]


def _detemplated_pair(pair: EvidenceQAPair, *, chunks_by_id: dict[str, PaperChunk]) -> EvidenceQAPair:
    source_chunk = _first_gold_chunk(pair, chunks_by_id)
    question = _blind_question_for_pair(pair, source_chunk)
    metadata = {
        **dict(pair.metadata),
        "question_profile": "blind_detemplated",
        "blind_evaluation": True,
        "detemplated": True,
        "detemplate_policy": "remove_labels_caption_quote_v1",
        "template_question": pair.question,
    }
    if source_chunk is not None:
        metadata["detemplate_source_chunk_type"] = source_chunk.chunk_type
        if source_chunk.section_title:
            metadata["detemplate_section_title"] = source_chunk.section_title
    return replace(pair, question=question, metadata=metadata)


def _blind_semantic_pair(pair: EvidenceQAPair, *, chunks_by_id: dict[str, PaperChunk]) -> EvidenceQAPair:
    source_chunk = _first_gold_chunk(pair, chunks_by_id)
    anchors, anchor_sources = _semantic_anchors_for_pair(pair, source_chunk, chunks_by_id)
    question = _blind_semantic_question_for_pair(pair, source_chunk, anchors)
    metadata = {
        **dict(pair.metadata),
        "question_profile": "blind_semantic",
        "blind_evaluation": True,
        "detemplated": True,
        "detemplate_policy": "semantic_anchors_no_labels_v1",
        "template_question": pair.question,
        "semantic_anchors": anchors,
        "semantic_anchor_sources": anchor_sources,
    }
    if source_chunk is not None:
        metadata["detemplate_source_chunk_type"] = source_chunk.chunk_type
        if source_chunk.section_title:
            metadata["detemplate_section_title"] = source_chunk.section_title
    return replace(pair, question=question, metadata=metadata)


def _first_gold_chunk(pair: EvidenceQAPair, chunks_by_id: dict[str, PaperChunk]) -> PaperChunk | None:
    for chunk_id in pair.gold_chunk_ids:
        chunk = chunks_by_id.get(chunk_id)
        if chunk is not None:
            return chunk
    return None


def _attach_evidence_groups(
    pairs: list[EvidenceQAPair],
    *,
    chunks_by_id: dict[str, PaperChunk],
) -> list[EvidenceQAPair]:
    return [_with_evidence_group(pair, chunks_by_id=chunks_by_id) for pair in pairs]


def _with_evidence_group(pair: EvidenceQAPair, *, chunks_by_id: dict[str, PaperChunk]) -> EvidenceQAPair:
    if pair.expected_behavior == _ABSTAIN_BEHAVIOR or not pair.gold_chunk_ids:
        return pair
    group = _build_supporting_evidence_group(pair, chunks_by_id=chunks_by_id)
    equivalent_ids = _unique_texts([
        *pair.gold_chunk_ids,
        *pair.equivalent_gold_chunk_ids,
        *group["equivalent_evidence_ids"],
    ])
    acceptable_ids = _unique_texts([
        *pair.acceptable_support_evidence_ids,
        *(
            chunk_id
            for chunk_id in equivalent_ids
            if chunk_id not in set(pair.gold_chunk_ids)
        ),
    ])
    return replace(
        pair,
        supporting_evidence_group_id=str(group["group_id"]),
        equivalent_gold_chunk_ids=equivalent_ids,
        required_primary_evidence_ids=pair.required_primary_evidence_ids or list(pair.gold_chunk_ids),
        acceptable_support_evidence_ids=acceptable_ids,
        gold_claim_ids=pair.gold_claim_ids or _gold_claim_ids_for_pair(pair, chunks_by_id=chunks_by_id),
        supporting_evidence_group=group,
        metadata={
            **dict(pair.metadata),
            "supporting_evidence_group_id": str(group["group_id"]),
            "equivalent_gold_chunk_count": len(equivalent_ids),
        },
    )


def _build_supporting_evidence_group(
    pair: EvidenceQAPair,
    *,
    chunks_by_id: dict[str, PaperChunk],
) -> dict[str, Any]:
    primary_ids = _unique_texts(pair.gold_chunk_ids)
    equivalent_ids: list[str] = list(primary_ids)
    interpretation_ids: list[str] = []
    relations: list[dict[str, str]] = []
    locator_context: list[dict[str, str]] = []

    def add_related(source: PaperChunk, target_id: str, edge: str) -> None:
        target = chunks_by_id.get(target_id)
        if target is None or target.paper_id != pair.paper_id:
            return
        equivalent_ids.append(target.chunk_id)
        if target.chunk_id not in primary_ids:
            interpretation_ids.append(target.chunk_id)
        relations.append({
            "from_chunk_id": source.chunk_id,
            "to_chunk_id": target.chunk_id,
            "edge": edge,
        })

    for chunk_id in primary_ids:
        chunk = chunks_by_id.get(chunk_id)
        if chunk is None or chunk.paper_id != pair.paper_id:
            continue
        source_locator = _source_locator_for_chunk(chunk)
        if source_locator:
            locator_context.append({
                "chunk_id": chunk.chunk_id,
                "source_locator": source_locator,
                "chunk_type": chunk.chunk_type,
            })
        if chunk.parent_chunk_id:
            add_related(chunk, chunk.parent_chunk_id, "parent_chunk_id")
        for ref_id in chunk.references:
            add_related(chunk, ref_id, "chunk_reference")
        for related_id in _related_context_ids(chunk):
            add_related(chunk, related_id, "related_context")
        for related in _same_specific_locator_chunks(chunk, chunks_by_id):
            add_related(chunk, related.chunk_id, "same_specific_source_locator")

    equivalent_ids = _unique_texts(equivalent_ids)
    interpretation_ids = _unique_texts(interpretation_ids)
    group_id = _evidence_group_id(pair, equivalent_ids)
    return {
        "group_id": group_id,
        "paper_id": pair.paper_id,
        "qa_type": pair.qa_type,
        "primary_evidence_ids": primary_ids,
        "equivalent_evidence_ids": equivalent_ids,
        "interpretation_context_ids": interpretation_ids,
        "locator_context": locator_context,
        "relations": relations,
    }


def _same_specific_locator_chunks(
    chunk: PaperChunk,
    chunks_by_id: dict[str, PaperChunk],
) -> list[PaperChunk]:
    locator = _source_locator_for_chunk(chunk)
    if not _is_specific_source_locator(locator):
        return []
    return [
        candidate
        for candidate in chunks_by_id.values()
        if candidate.chunk_id != chunk.chunk_id
        and candidate.paper_id == chunk.paper_id
        and _source_locator_for_chunk(candidate) == locator
    ]


def _is_specific_source_locator(locator: str) -> bool:
    text = str(locator or "").casefold()
    return any(marker in text for marker in ("page=", "rect=", "#page", "bbox", "pdf#"))


def _evidence_group_id(pair: EvidenceQAPair, equivalent_ids: list[str]) -> str:
    payload = json.dumps({
        "paper_id": pair.paper_id,
        "qa_type": pair.qa_type,
        "gold": pair.gold_chunk_ids,
        "equivalent": equivalent_ids,
    }, ensure_ascii=False, sort_keys=True)
    return "eg_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _gold_claim_ids_for_pair(pair: EvidenceQAPair, *, chunks_by_id: dict[str, PaperChunk]) -> list[str]:
    if pair.qa_type != "citation_qa":
        return []
    records = []
    for chunk_id in pair.gold_chunk_ids:
        chunk = chunks_by_id.get(chunk_id)
        if chunk is None or chunk.paper_id != pair.paper_id:
            continue
        records.extend(extract_claim_records(chunk))
    return _unique_texts([record.claim_id for record in records])


def _blind_semantic_question_for_pair(
    pair: EvidenceQAPair,
    chunk: PaperChunk | None,
    anchors: list[str],
) -> str:
    section_hint = _natural_section_hint(chunk)
    anchor_phrase = _anchor_phrase(anchors)
    if pair.expected_behavior == _ABSTAIN_BEHAVIOR:
        return "Is there evidence in this paper for an unrelated future model that the paper itself does not discuss?"
    if pair.qa_type == "table_qa":
        if anchor_phrase:
            return f"What quantitative evidence does the paper report about {anchor_phrase}?"
        return f"What quantitative evidence does the paper report in {section_hint}?"
    if pair.qa_type == "experiment_result_qa":
        if anchor_phrase:
            return f"What do the reported results about {anchor_phrase} suggest overall?"
        return f"What do the reported experiments in {section_hint} suggest overall?"
    if pair.qa_type == "figure_qa":
        if anchor_phrase:
            return f"What visual evidence does the paper use to explain {anchor_phrase}?"
        return f"What visual evidence explains the model, process, or behavior discussed in {section_hint}?"
    if pair.qa_type == "formula_qa":
        if anchor_phrase:
            return f"How does the paper define the mathematical relation for {anchor_phrase}?"
        return f"How does the paper define the key mathematical relation used in {section_hint}?"
    if pair.qa_type == "formula_explanation_qa":
        if anchor_phrase:
            return f"How does the surrounding text explain the mathematical relation for {anchor_phrase}?"
        return f"How does the surrounding text explain the mathematical relation in {section_hint}?"
    if pair.qa_type == "citation_qa":
        if anchor_phrase:
            return f"Which passage grounds the paper's claim about {anchor_phrase}?"
        return f"Which passage grounds the main claim made in {section_hint}?"
    if anchor_phrase:
        return f"What evidence answers the question about {anchor_phrase}?"
    return f"What evidence in {section_hint} answers this question?"


def _semantic_anchors_for_pair(
    pair: EvidenceQAPair,
    chunk: PaperChunk | None,
    chunks_by_id: dict[str, PaperChunk],
) -> tuple[list[str], list[str]]:
    candidates: list[tuple[str, str]] = []
    if pair.qa_type in {"table_qa", "experiment_result_qa"}:
        candidates.extend(_table_anchor_candidates(pair, chunk))
    elif pair.qa_type == "figure_qa":
        candidates.extend(_figure_anchor_candidates(pair, chunk))
    elif pair.qa_type in {"formula_qa", "formula_explanation_qa"}:
        candidates.extend(_formula_anchor_candidates(pair, chunk, chunks_by_id))
    elif pair.qa_type == "citation_qa":
        candidates.extend(("answer_fact", fact) for fact in pair.answer_facts)
    else:
        candidates.extend(("answer_fact", fact) for fact in pair.answer_facts)
        if chunk is not None:
            candidates.append(("content", chunk.content))

    anchors: list[str] = []
    sources: list[str] = []
    for source, text in candidates:
        for anchor in _semantic_anchor_terms(text):
            if anchor in anchors:
                continue
            anchors.append(anchor)
            if source not in sources:
                sources.append(source)
            if len(anchors) >= 6:
                return anchors, sources
    return anchors, sources


def _table_anchor_candidates(pair: EvidenceQAPair, chunk: PaperChunk | None) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    topic = str(pair.metadata.get("table_topic") or "")
    if topic:
        candidates.append(("metadata.table_topic", topic))
    if chunk is None:
        candidates.extend(("answer_fact", fact) for fact in pair.answer_facts)
        return candidates
    trusted_caption = _trusted_caption_for_chunk(chunk)
    candidates.extend([
        ("trusted_caption", trusted_caption),
        ("metadata.semantic_text", str(chunk.metadata.get("semantic_text") or "")),
        ("metadata.table_text", str(chunk.metadata.get("table_text") or "")),
        ("metadata.columns", _metadata_text(chunk.metadata.get("columns"))),
        ("metadata.rows", _metadata_text(chunk.metadata.get("rows"))),
        ("content.caption", _caption_from_content(chunk.content)),
        ("content", chunk.content),
    ])
    candidates.extend(("answer_fact", fact) for fact in pair.answer_facts)
    return candidates


def _figure_anchor_candidates(pair: EvidenceQAPair, chunk: PaperChunk | None) -> list[tuple[str, str]]:
    if chunk is None:
        return [("answer_fact", fact) for fact in pair.answer_facts]
    candidates = [
        ("metadata.visual_description", str(chunk.metadata.get("visual_description") or "")),
        ("trusted_caption", _trusted_caption_for_chunk(chunk)),
        ("content.caption", _caption_from_content(chunk.content)),
        ("content", chunk.content),
    ]
    candidates.extend(("answer_fact", fact) for fact in pair.answer_facts)
    return candidates


def _formula_anchor_candidates(
    pair: EvidenceQAPair,
    chunk: PaperChunk | None,
    chunks_by_id: dict[str, PaperChunk],
) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    if chunk is not None:
        candidates.extend([
            ("formula_description", chunk.formula_description),
            ("section_title", chunk.section_title),
        ])
    for chunk_id in pair.gold_chunk_ids:
        context = chunks_by_id.get(chunk_id)
        if context is None or context is chunk:
            continue
        candidates.append(("gold_context", context.content))
    if chunk is not None:
        candidates.extend([
            ("metadata.formula_referenced_text", _metadata_text(chunk.metadata.get("formula_referenced_text"))),
            ("metadata.formula_symbols", _metadata_text(chunk.metadata.get("formula_symbols"))),
            ("metadata.formula_operators", _metadata_text(chunk.metadata.get("formula_operators"))),
            ("formula_latex", chunk.formula_latex),
            ("content", chunk.content),
        ])
    candidates.extend(("answer_fact", fact) for fact in pair.answer_facts)
    return candidates


def _metadata_text(value: object) -> str:
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                parts.extend(str(part) for part in item.values() if str(part).strip())
            else:
                text = str(item).strip()
                if text:
                    parts.append(text)
        return " ".join(parts)
    if isinstance(value, dict):
        return " ".join(str(part) for part in value.values() if str(part).strip())
    return str(value or "")


def _trusted_caption_for_chunk(chunk: PaperChunk) -> str:
    content_caption = _caption_from_content(chunk.content)
    metadata_caption = str(chunk.metadata.get("caption_text") or chunk.metadata.get("surya_caption") or "")
    if content_caption and metadata_caption and not _captions_are_compatible(content_caption, metadata_caption):
        return content_caption
    return content_caption or metadata_caption


def _captions_are_compatible(left: str, right: str) -> bool:
    left_tokens = _caption_signature_tokens(left)
    right_tokens = _caption_signature_tokens(right)
    if not left_tokens or not right_tokens:
        return True
    overlap = len(left_tokens & right_tokens)
    smaller = min(len(left_tokens), len(right_tokens))
    return overlap >= 2 or (smaller > 0 and overlap / smaller >= 0.4)


def _caption_signature_tokens(text: str) -> set[str]:
    tokens = {
        token.casefold()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", _strip_element_labels(str(text or "")))
        if _is_semantic_anchor_token(token)
    }
    return tokens


def _semantic_anchor_terms(text: str) -> list[str]:
    cleaned = _strip_element_labels(str(text or ""))
    cleaned = re.sub(r"\\(?:begin|end)\{[^{}]*\}", " ", cleaned)
    cleaned = re.sub(r"\\(?:label|ref|cite|caption)\{[^{}]*\}", " ", cleaned)
    cleaned = re.sub(r"\\(?:mathcal|mathrm|mathbf|mathbb|text|operatorname|boldsymbol)\{([^{}]*)\}", r"\1", cleaned)
    cleaned = cleaned.replace("\\", " ")
    tokens = [
        token
        for token in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", cleaned)
        if _is_semantic_anchor_token(token)
    ]
    anchors: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        normalized = token.casefold().strip("-_")
        if normalized in seen:
            continue
        anchors.append(token.strip("-_"))
        seen.add(normalized)
        if len(anchors) >= 6:
            break
    return anchors


def _strip_element_labels(text: str) -> str:
    cleaned = re.sub(r"\[(?:figure|fig\.?|table|equation|eq\.?)\s+[^\]]+\]", " ", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:figure|fig\.?|table|equation|eq\.?)\s+[A-Za-z0-9_.:-]+\b[:.]?", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:fig|tbl|eq)_[A-Za-z0-9_-]+\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\blabel\{[^{}]*\}", " ", cleaned, flags=re.IGNORECASE)
    return cleaned


def _is_semantic_anchor_token(token: str) -> bool:
    normalized = token.casefold().strip("-_")
    if len(normalized) < 3:
        return False
    stopwords = {
        "about", "above", "across", "after", "again", "against", "align", "also", "although", "among",
        "answer", "around", "available", "because", "before", "begin", "being", "below",
        "between", "briefly", "can", "caption", "cdot", "chunk", "column", "columns", "compared",
        "concretely", "contains", "context", "could", "dataset", "define", "defined", "denote",
        "denotes", "describe", "despite", "does",
        "each", "end", "equation", "figure", "formula", "frac", "from", "given", "have",
        "here", "into", "introduces", "label", "latex", "left", "let", "many", "mathbb", "mathcal", "mathbf", "mathrm", "method",
        "model", "models", "nabla", "normalized", "operator", "operatorname", "operators",
        "original", "paper", "paragraph", "reported", "result", "results", "right", "row", "rows",
        "section", "show", "shows", "some", "sqrt", "subsection", "symbols", "table", "text",
        "that", "their", "there", "these", "this", "using", "where", "which", "whenever",
        "with", "within",
        "and", "are", "for", "new", "next", "now", "one", "our", "the",
    }
    if normalized in stopwords:
        return False
    if normalized.startswith(("fig", "tbl", "eq_")) and any(char.isdigit() for char in normalized):
        return False
    return True


def _anchor_phrase(anchors: list[str]) -> str:
    selected = [anchor for anchor in anchors if anchor.strip()][:6]
    if not selected:
        return ""
    if len(selected) == 1:
        return selected[0]
    if len(selected) == 2:
        return f"{selected[0]} and {selected[1]}"
    return ", ".join(selected[:-1]) + f", and {selected[-1]}"


def _blind_question_for_pair(pair: EvidenceQAPair, chunk: PaperChunk | None) -> str:
    section_hint = _natural_section_hint(chunk)
    if pair.expected_behavior == _ABSTAIN_BEHAVIOR:
        return "Is there evidence in this paper for an unrelated future model that the paper itself does not discuss?"
    if pair.qa_type == "table_qa":
        return f"What quantitative evidence does the paper use in {section_hint}, and what is the takeaway?"
    if pair.qa_type == "experiment_result_qa":
        return f"What do the reported experiments in {section_hint} suggest overall?"
    if pair.qa_type == "figure_qa":
        return f"What visual evidence explains the model, process, or behavior discussed in {section_hint}?"
    if pair.qa_type == "formula_qa":
        return f"How does the paper define the key mathematical relation used in {section_hint}?"
    if pair.qa_type == "formula_explanation_qa":
        return f"How does the surrounding text explain the mathematical relation in {section_hint}?"
    if pair.qa_type == "citation_qa":
        topic = _claim_topic(pair.answer_facts[0] if pair.answer_facts else "")
        if topic:
            return f"Which passage grounds the paper's claim about {topic}?"
        return f"Which passage grounds the main claim made in {section_hint}?"
    return f"What evidence in {section_hint} answers this question?"


def _natural_section_hint(chunk: PaperChunk | None) -> str:
    if chunk is None:
        return "the paper"
    roles = [str(role).replace("_", " ") for role in chunk.section_role if str(role).strip()]
    if roles:
        role = roles[0]
        return f"the {role} section"
    title = " ".join(str(chunk.section_title or "").split())
    if title:
        cleaned = re.sub(r"^\d+(?:\.\d+)*\s*", "", title).strip()
        if cleaned:
            return f"the {cleaned} section"
    return "the paper"


def _claim_topic(text: str) -> str:
    stopwords = {
        "this",
        "that",
        "with",
        "from",
        "have",
        "into",
        "their",
        "there",
        "where",
        "which",
        "paper",
        "model",
        "models",
        "using",
        "used",
        "show",
        "shows",
        "result",
        "results",
    }
    tokens = []
    seen: set[str] = set()
    for token in re.findall(r"[A-Za-z][A-Za-z0-9-]{3,}", str(text or "")):
        normalized = token.casefold()
        if normalized in stopwords or normalized in seen:
            continue
        tokens.append(token)
        seen.add(normalized)
        if len(tokens) >= 4:
            break
    return " ".join(tokens)


def _template_pair_for_chunk(
    chunk: PaperChunk,
    qa_type: str,
    *,
    domain: str,
    chunks_by_id: dict[str, PaperChunk],
) -> EvidenceQAPair | None:
    if qa_type == "formula_qa":
        return _formula_pair(chunk, domain=domain)
    if qa_type == "table_qa":
        return _visual_or_table_pair(chunk, qa_type="table_qa", domain=domain, chunks_by_id=chunks_by_id)
    if qa_type == "figure_qa":
        if not _has_interpretable_figure_text(chunk):
            return None
        return _visual_or_table_pair(chunk, qa_type="figure_qa", domain=domain, chunks_by_id=chunks_by_id)
    if qa_type == "citation_qa":
        return _citation_pair(chunk, domain=domain)
    return None


def _formula_pair(chunk: PaperChunk, *, domain: str) -> EvidenceQAPair:
    label = _element_label(chunk, fallback="the formula")
    question_label = _formula_question_label(label)
    answer_facts = [chunk.formula_description] if chunk.formula_description else []
    if not answer_facts and chunk.formula_latex:
        answer_facts = [chunk.formula_latex]
    return EvidenceQAPair.from_source_chunk(
        question=f"What does {question_label} mean in this paper?",
        chunk=chunk,
        qa_type="formula_qa",
        required_evidence_types=["formula"],
        answer_facts=answer_facts,
        difficulty="medium",
        domain=domain,
        metadata={"builder": "deterministic_template"},
    )


def _formula_explanation_pair(
    chunk: PaperChunk,
    *,
    domain: str,
    chunks_by_id: dict[str, PaperChunk],
) -> EvidenceQAPair | None:
    context_chunks = _referenced_context_chunks(chunk, chunks_by_id)
    if not context_chunks:
        return None
    label = _element_label(chunk, fallback="the formula")
    equation_label = _formula_question_label(label)
    return EvidenceQAPair(
        question=f"How is {equation_label} explained in the surrounding text?",
        paper_id=chunk.paper_id,
        qa_type="formula_explanation_qa",
        gold_chunk_ids=_unique_texts([chunk.chunk_id, *(context.chunk_id for context in context_chunks)]),
        required_evidence_types=_unique_texts([
            "formula",
            *(_support_context_evidence_type(context) for context in context_chunks),
        ]),
        gold_source_locators=_unique_texts([
            _source_locator_for_chunk(chunk),
            *(_source_locator_for_chunk(context) for context in context_chunks),
        ]),
        answer_facts=_unique_texts([
            *_answer_facts_from_chunk(chunk),
            *(
                _formula_context_fact(chunk, context)
                for context in context_chunks[:2]
            ),
        ])[:3],
        expected_behavior=_ANSWER_BEHAVIOR,
        difficulty="medium",
        domain=domain,
        metadata={
            "builder": "deterministic_template",
            "source_qa_type": "formula_explanation_context",
        },
    )


def _formula_question_label(label: str) -> str:
    normalized = label.strip()
    if not normalized:
        return "the formula"
    if any(token in normalized.casefold() for token in ("equation", "formula")):
        return normalized
    return f"Equation {normalized}"


def _typed_element_label(label: str, *, element_type: str) -> str:
    normalized = label.strip()
    if not normalized:
        return f"the {element_type}"
    lowered = normalized.casefold()
    if re.search(rf"\b{re.escape(element_type)}\.?\b", lowered):
        return normalized
    return f"{element_type.title()} {normalized}"


def _formula_context_fact(formula_chunk: PaperChunk, context: PaperChunk) -> str:
    sentences = _formula_context_window_sentences(formula_chunk, context)
    if not sentences:
        return _snippet_from_content(context.content)
    formula_terms = _formula_terms(formula_chunk)
    best_index = 0
    best_score = -1
    for index, sentence in enumerate(sentences):
        lowered = sentence.casefold()
        tokens = set(_fact_tokens(sentence))
        term_hits = len(tokens & formula_terms)
        explanation_hits = sum(
            1
            for keyword in (
                "where",
                "denote",
                "denotes",
                "represent",
                "represents",
                "defined",
                "means",
                "is the",
                "are the",
                "incorporate",
                "computed",
            )
            if keyword in lowered
        )
        score = term_hits * 2 + explanation_hits
        if score > best_score:
            best_score = score
            best_index = index
    selected = sentences[best_index]
    if best_index + 1 < len(sentences) and len(selected) < 220:
        next_sentence = sentences[best_index + 1]
        if _formula_sentence_related(next_sentence, formula_terms):
            selected = f"{selected} {next_sentence}"
    return _snippet_from_content(selected, max_chars=260)


def _formula_context_window_sentences(formula_chunk: PaperChunk, context: PaperChunk) -> list[str]:
    content = str(context.content or "")
    position = _formula_anchor_position(formula_chunk, content)
    if position < 0:
        return _fact_sentences(content)
    window = content[max(0, position - 600):position + 1800]
    return _fact_sentences(window)


def _formula_anchor_position(formula_chunk: PaperChunk, content: str) -> int:
    candidates = _unique_texts([
        *_formula_label_candidates(formula_chunk),
        str(formula_chunk.metadata.get("equation_label") or ""),
        str(formula_chunk.metadata.get("equation_id") or ""),
    ])
    for candidate in candidates:
        if not candidate:
            continue
        index = content.find(candidate)
        if index >= 0:
            return index
    latex_tokens = [
        token
        for token in _fact_tokens(formula_chunk.formula_latex or formula_chunk.content)
        if len(token) >= 4
    ][:6]
    if not latex_tokens:
        return -1
    lowered = content.casefold()
    best_index = -1
    best_hits = 0
    for match in re.finditer(r"\\begin\{(?:equation|align|gather)[*]?\}|\\\[|\$\$", content):
        start = match.start()
        window = lowered[start:start + 1200]
        hits = sum(1 for token in latex_tokens if token in window)
        if hits > best_hits:
            best_hits = hits
            best_index = start
    return best_index if best_hits >= 2 else -1


def _formula_label_candidates(chunk: PaperChunk) -> list[str]:
    values = [
        str(chunk.metadata.get("equation_label") or ""),
        str(chunk.metadata.get("equation_id") or ""),
        str(chunk.metadata.get("element_label") or ""),
    ]
    for source in (chunk.formula_latex, chunk.content):
        values.extend(re.findall(r"\\label\{([^{}]+)\}", str(source or "")))
    return _unique_texts(values)


def _fact_sentences(content: str) -> list[str]:
    text = re.sub(
        r"\\begin\{(?:equation|align|gather)[*]?\}.*?\\end\{(?:equation|align|gather)[*]?\}",
        " ",
        str(content or ""),
        flags=re.DOTALL,
    )
    text = re.sub(r"\$\$.*?\$\$", " ", text, flags=re.DOTALL)
    candidates = re.split(r"(?<=[.!?])\s+|\n{2,}", text)
    out = [" ".join(candidate.split()) for candidate in candidates if len(candidate.split()) >= 5]
    return out


def _formula_terms(chunk: PaperChunk) -> set[str]:
    text = " ".join([
        chunk.formula_latex,
        str(chunk.metadata.get("equation_label") or ""),
        str(chunk.metadata.get("reference_labels") or ""),
    ])
    return {
        token
        for token in _fact_tokens(text)
        if len(token) > 1 and token not in {"begin", "end", "equation", "label", "left", "right"}
    }


def _fact_tokens(text: str) -> list[str]:
    cleaned = re.sub(r"\\label\{[^{}]*\}", " ", str(text or ""))
    cleaned = re.sub(r"_\{([^}]+)\}", r"_\1", cleaned)
    cleaned = re.sub(r"\^\{([^}]+)\}", r"_\1", cleaned)
    cleaned = re.sub(r"\\([A-Za-z]+)_([A-Za-z0-9]+)", r" \1_\2 ", cleaned)
    cleaned = re.sub(r"\\(?:mathbf|mathrm|mathcal|mathbb|text|operatorname|boldsymbol)\{([^{}]*)\}", r"\1", cleaned)
    cleaned = cleaned.replace("\\", " ")
    return [token.casefold() for token in re.findall(r"[A-Za-z0-9_]+", cleaned)]


def _formula_sentence_related(sentence: str, formula_terms: set[str]) -> bool:
    tokens = set(_fact_tokens(sentence))
    if tokens & formula_terms:
        return True
    lowered = sentence.casefold()
    return any(keyword in lowered for keyword in ("where", "denote", "represent", "defined", "means"))


def _table_question(label: str, chunk: PaperChunk) -> str:
    topic = _visual_question_topic(chunk)
    if topic:
        return f"What do the experimental results around {label}, about {topic}, show?"
    return f"What do the experimental results around {label} show?"


def _figure_question(label: str, chunk: PaperChunk) -> str:
    topic = _visual_question_topic(chunk)
    if topic:
        return f"What does {label}, captioned {topic}, show?"
    return f"What does {label} show?"


def _visual_question_topic(chunk: PaperChunk) -> str:
    topic = _caption_from_content(chunk.content)
    if not topic:
        topic = _trusted_caption_for_chunk(chunk)
    topic = " ".join(topic.split())
    if len(topic) > 140:
        topic = topic[:140].rsplit(" ", 1)[0].strip()
    return topic


def _has_interpretable_figure_text(chunk: PaperChunk) -> bool:
    description = str(chunk.metadata.get("visual_description") or "")
    if _meaningful_visual_text(description):
        return True
    caption = _trusted_caption_for_chunk(chunk)
    return _meaningful_visual_text(caption) and not _caption_looks_incomplete(caption)


def _meaningful_visual_text(text: str) -> bool:
    words = re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", str(text or ""))
    return len(words) >= 1


def _caption_looks_incomplete(text: str) -> bool:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return True
    if normalized.endswith(("\\", "/", ":", ",", ";", "(")):
        return True
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9-]*", normalized.casefold())
    if not tokens:
        return True
    return tokens[-1] in {
        "between",
        "among",
        "across",
        "with",
        "without",
        "for",
        "from",
        "into",
        "over",
        "under",
        "and",
        "or",
        "the",
        "a",
        "an",
        "of",
        "to",
    }


def _visual_or_table_pair(
    chunk: PaperChunk,
    *,
    qa_type: str,
    domain: str,
    chunks_by_id: dict[str, PaperChunk],
) -> EvidenceQAPair:
    is_table = qa_type == "table_qa"
    label = _typed_element_label(
        _element_label(chunk, fallback="the table" if is_table else "the figure"),
        element_type="table" if is_table else "figure",
    )
    question = (
        _table_question(label, chunk)
        if is_table
        else _figure_question(label, chunk)
    )
    gold_ids = [chunk.chunk_id]
    required_types = ["table" if is_table else "figure"]
    related_context_chunks: list[PaperChunk] = []
    for related_id in _related_context_ids(chunk):
        related = chunks_by_id.get(related_id)
        if related is None or not _is_contentful_related_context_chunk(related):
            continue
        gold_ids.append(related.chunk_id)
        related_context_chunks.append(related)
        evidence_type = _evidence_type_for_chunk(related)
        if evidence_type not in required_types:
            required_types.append(evidence_type)
    return EvidenceQAPair(
        question=question,
        paper_id=chunk.paper_id,
        qa_type=qa_type,
        gold_chunk_ids=gold_ids,
        required_evidence_types=required_types,
        gold_source_locators=_unique_texts([_source_locator_for_chunk(chunk)]),
        gold_image_refs=_unique_texts([_image_ref_for_chunk(chunk)]),
        answer_facts=_unique_texts([
            *_answer_facts_from_chunk(chunk),
            *(_snippet_from_content(context.content, max_chars=260) for context in related_context_chunks[:2]),
        ])[:3],
        expected_behavior=_ANSWER_BEHAVIOR,
        difficulty="medium",
        domain=domain,
        metadata={"builder": "deterministic_template"},
    )


def _experiment_result_pair(
    chunk: PaperChunk,
    *,
    domain: str,
    chunks_by_id: dict[str, PaperChunk],
) -> EvidenceQAPair | None:
    if not _is_experiment_result_table(chunk):
        return None
    context_chunks = _explicit_result_reference_chunks(chunk, chunks_by_id)
    label = _typed_element_label(_element_label(chunk, fallback="the table"), element_type="table")
    topic = _experiment_table_topic(chunk)
    question = (
        f"What do the experiment results around {label} show overall?"
        if not topic
        else f"What do the experiment results around {label}, about {topic}, show overall?"
    )
    gold_ids = _unique_texts([chunk.chunk_id, *(context.chunk_id for context in context_chunks)])
    required_types = _unique_texts(["table", *(_evidence_type_for_chunk(context) for context in context_chunks)])
    return EvidenceQAPair(
        question=question,
        paper_id=chunk.paper_id,
        qa_type="experiment_result_qa",
        gold_chunk_ids=gold_ids,
        required_evidence_types=required_types,
        gold_source_locators=_unique_texts([
            _source_locator_for_chunk(chunk),
            *(_source_locator_for_chunk(context) for context in context_chunks),
        ]),
        gold_image_refs=_unique_texts([_image_ref_for_chunk(chunk)]),
        answer_facts=_unique_texts([
            *_answer_facts_from_chunk(chunk),
            *(_snippet_from_content(context.content) for context in context_chunks[:2]),
        ])[:3],
        expected_behavior=_ANSWER_BEHAVIOR,
        difficulty="medium",
        domain=domain,
        metadata={
            "builder": "deterministic_template",
            "source_qa_type": "table_result_context",
            "context_source": "explicit_reference" if context_chunks else "table_only",
            "table_topic": topic,
        },
    )


def _balanced_by_paper(pairs: list[EvidenceQAPair], max_count: int) -> list[EvidenceQAPair]:
    if len(pairs) <= max_count:
        return pairs
    buckets: dict[str, list[EvidenceQAPair]] = {}
    for pair in pairs:
        buckets.setdefault(pair.paper_id, []).append(pair)
    selected: list[EvidenceQAPair] = []
    paper_ids = sorted(buckets)
    while len(selected) < max_count:
        progressed = False
        for paper_id in paper_ids:
            bucket = buckets[paper_id]
            if not bucket:
                continue
            selected.append(bucket.pop(0))
            progressed = True
            if len(selected) >= max_count:
                break
        if not progressed:
            break
    return selected


def _citation_pair(chunk: PaperChunk, *, domain: str) -> EvidenceQAPair | None:
    source_locator = _source_locator_for_chunk(chunk)
    if not source_locator:
        return None
    snippet = _clean_citation_claim(_snippet_from_content(chunk.content))
    if not _is_contentful_citation_claim(snippet):
        return None
    citation_span = {
        "chunk_id": chunk.chunk_id,
        "snippet": snippet,
        "span_kind": "main",
        "resolved_chunk_id": chunk.chunk_id,
        "resolved_source_locator": source_locator,
    }
    return EvidenceQAPair(
        question=f"Which evidence supports the claim: {snippet}",
        paper_id=chunk.paper_id,
        qa_type="citation_qa",
        gold_chunk_ids=[chunk.chunk_id],
        required_evidence_types=[_evidence_type_for_chunk(chunk)],
        gold_source_locators=[source_locator],
        gold_citation_spans=[citation_span],
        answer_facts=[snippet],
        expected_behavior=_ANSWER_BEHAVIOR,
        difficulty="easy",
        domain=domain,
        metadata={"builder": "deterministic_template"},
    )


def _aggregate_samples(
    samples: list[EvidenceSampleResult],
    *,
    ks: tuple[int, ...],
) -> EvidenceEvalResult:
    answerable = [sample for sample in samples if sample.is_answerable]
    result = EvidenceEvalResult(
        total=len(samples),
        answerable_total=len(answerable),
        abstain_total=len(samples) - len(answerable),
        ks=ks,
        hit_at={k: 0 for k in ks},
        equivalent_hit_at={k: 0 for k in ks},
        evidence_coverage_at={k: [] for k in ks},
        equivalent_evidence_coverage_at={k: [] for k in ks},
        required_type_coverage_at={k: [] for k in ks},
        source_locator_coverage_at={k: [] for k in ks},
        image_recall_at={k: [] for k in ks},
        visual_evidence_coverage_at={k: [] for k in ks},
        citation_accuracy_at={k: [] for k in ks},
        overlap_citation_accuracy_at={k: [] for k in ks},
        over_retrieval_at={k: [] for k in ks},
        ndcg_at={k: [] for k in ks},
        samples=list(samples),
    )
    result.intent_distribution = _intent_distribution(samples)
    result.route_distribution = _route_distribution(samples)
    result.intent_confusion = _intent_confusion(samples)
    for sample in answerable:
        metric_case = _retrieval_metric_case(sample)
        equivalent_metric_case = _equivalent_retrieval_metric_case(sample)
        result.reciprocal_ranks.append(kernel_reciprocal_rank(metric_case))
        result.equivalent_reciprocal_ranks.append(kernel_reciprocal_rank(equivalent_metric_case))
        for k in ks:
            if kernel_hit_at_k(metric_case, k):
                result.hit_at[k] += 1
            if kernel_hit_at_k(equivalent_metric_case, k):
                result.equivalent_hit_at[k] += 1
            result.evidence_coverage_at[k].append(kernel_evidence_coverage(metric_case, k))
            result.equivalent_evidence_coverage_at[k].append(kernel_evidence_coverage(equivalent_metric_case, k))
            result.required_type_coverage_at[k].append(sample.type_coverage_by_k[k])
            result.source_locator_coverage_at[k].append(kernel_source_locator_coverage(metric_case, k))
            if sample.pair.gold_image_refs:
                result.image_recall_at[k].append(sample.image_recall_by_k[k])
                result.visual_evidence_coverage_at[k].append(sample.visual_evidence_coverage_by_k[k])
            citation_accuracy = sample.citation_accuracy_by_k.get(k)
            if citation_accuracy is not None:
                result.citation_accuracy_at[k].append(citation_accuracy)
            overlap_accuracy = sample.overlap_citation_accuracy_by_k.get(k)
            if overlap_accuracy is not None:
                result.overlap_citation_accuracy_at[k].append(overlap_accuracy)
            result.over_retrieval_at[k].append(sample.over_retrieval_by_k[k])
            result.ndcg_at[k].append(kernel_ndcg_at_k(metric_case, k))
    return result


def _intent_distribution(samples: list[EvidenceSampleResult]) -> dict[str, int]:
    counts = Counter(
        sample.retrieval_intent
        for sample in samples
        if sample.retrieval_intent
    )
    return dict(sorted(counts.items()))


def _route_distribution(samples: list[EvidenceSampleResult]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for sample in samples:
        for route in sample.recall_routes:
            counts[route] += 1
    return dict(sorted(counts.items()))


def _intent_confusion(samples: list[EvidenceSampleResult]) -> dict[str, dict[str, int]]:
    matrix: dict[str, Counter[str]] = {}
    for sample in samples:
        if not sample.retrieval_intent:
            continue
        matrix.setdefault(sample.pair.qa_type, Counter())[sample.retrieval_intent] += 1
    return {
        qa_type: dict(sorted(counts.items()))
        for qa_type, counts in sorted(matrix.items())
    }


def _retrieval_metric_case(sample: EvidenceSampleResult) -> RetrievalMetricCase:
    return RetrievalMetricCase(
        case_id=f"{sample.pair.paper_id}:{sample.pair.qa_type}:{sample.pair.question}",
        gold_evidence_ids=tuple(sample.pair.gold_chunk_ids),
        ranked_evidence_ids=tuple(sample.ranked_chunk_ids),
        ranked_evidence_id_candidates=tuple(tuple(ids) for ids in sample.ranked_match_chunk_ids),
        gold_source_locators=tuple(sample.pair.gold_source_locators),
        ranked_source_locators=tuple(sample.ranked_source_locators),
        ranked_source_locator_candidates=tuple(
            tuple(locators) for locators in sample.ranked_source_locator_candidates
        ),
        metadata={
            "paper_id": sample.pair.paper_id,
            "qa_type": sample.pair.qa_type,
            "expected_behavior": sample.pair.expected_behavior,
        },
    )


def _equivalent_retrieval_metric_case(sample: EvidenceSampleResult) -> RetrievalMetricCase:
    equivalent_gold_ids = sample.pair.equivalent_gold_chunk_ids or sample.pair.gold_chunk_ids
    return RetrievalMetricCase(
        case_id=f"{sample.pair.paper_id}:{sample.pair.qa_type}:{sample.pair.question}:equivalent",
        gold_evidence_ids=tuple(equivalent_gold_ids),
        ranked_evidence_ids=tuple(sample.ranked_chunk_ids),
        ranked_evidence_id_candidates=tuple(tuple(ids) for ids in sample.ranked_match_chunk_ids),
        gold_source_locators=tuple(sample.pair.gold_source_locators),
        ranked_source_locators=tuple(sample.ranked_source_locators),
        ranked_source_locator_candidates=tuple(
            tuple(locators) for locators in sample.ranked_source_locator_candidates
        ),
        metadata={
            "paper_id": sample.pair.paper_id,
            "qa_type": sample.pair.qa_type,
            "expected_behavior": sample.pair.expected_behavior,
            "metric_scope": "equivalent_gold",
        },
    )


def _score_breakdown_for_chunk(chunk: PaperChunk) -> dict[str, float]:
    return paper_chunk_to_rag_evidence(chunk).score_breakdown.to_dict()


def iter_ranked_score_breakdowns(
    result: EvidenceEvalResult,
    *,
    top_k: int | None = None,
) -> Iterable[dict[str, float]]:
    for sample in result.samples:
        breakdowns = sample.ranked_score_breakdowns
        if top_k is not None:
            breakdowns = breakdowns[:top_k]
        for breakdown in breakdowns:
            yield breakdown


def formula_failure_diagnostics(
    result: EvidenceEvalResult,
    *,
    top_k: int = 10,
) -> dict[str, Any]:
    items = [
        _formula_failure_item(sample, top_k=top_k)
        for sample in result.samples
        if _is_formula_sample_failure(sample, top_k=top_k)
    ]
    reason_counts: Counter[str] = Counter()
    for item in items:
        reason_counts.update(item.get("failure_reasons") or [])
    return {
        "top_k": top_k,
        "total_failures": len(items),
        "reason_counts": dict(sorted(reason_counts.items())),
        "items": items,
    }


def _is_formula_sample_failure(sample: EvidenceSampleResult, *, top_k: int) -> bool:
    if sample.pair.expected_behavior != _ANSWER_BEHAVIOR:
        return False
    if sample.pair.qa_type not in {"formula_qa", "formula_explanation_qa"}:
        return False
    if sample.equivalent_first_rank and sample.equivalent_first_rank <= top_k:
        if sample.pair.qa_type != "formula_explanation_qa":
            return False
        return sample.equivalent_coverage_by_k.get(top_k, 0.0) < 1.0
    return True


def _formula_failure_item(sample: EvidenceSampleResult, *, top_k: int) -> dict[str, Any]:
    ranked_ids = sample.ranked_chunk_ids[:top_k]
    score_breakdowns = sample.ranked_score_breakdowns[:top_k]
    reasons = _formula_failure_reasons(sample, top_k=top_k)
    return {
        "paper_id": sample.pair.paper_id,
        "qa_type": sample.pair.qa_type,
        "question": sample.pair.question,
        "gold_chunk_ids": list(sample.pair.gold_chunk_ids),
        "equivalent_gold_chunk_ids": list(sample.pair.equivalent_gold_chunk_ids),
        "ranked_chunk_ids": ranked_ids,
        "first_gold_rank": sample.first_rank,
        "equivalent_first_gold_rank": sample.equivalent_first_rank,
        "evidence_coverage_at_k": sample.coverage_by_k.get(top_k, 0.0),
        "equivalent_evidence_coverage_at_k": sample.equivalent_coverage_by_k.get(top_k, 0.0),
        "failure_reasons": reasons,
        "suggested_action": _formula_failure_suggested_action(reasons),
        "score_breakdown": score_breakdowns,
        "retrieval_metadata": _formula_retrieval_metadata(sample.retrieval_metadata),
    }


def _formula_failure_reasons(sample: EvidenceSampleResult, *, top_k: int) -> list[str]:
    reasons: list[str] = []
    metadata = sample.retrieval_metadata
    if sample.retrieval_intent and sample.retrieval_intent != "formula_query":
        reasons.append("formula_intent_mismatch")
    if not metadata.get("formula_sparse_enabled"):
        reasons.append("formula_sparse_disabled")
    if not sample.equivalent_first_rank:
        reasons.append("missing_gold_in_retrieval")
    elif sample.equivalent_first_rank > top_k:
        reasons.append("reranker_demoted_gold")
    if sample.pair.qa_type == "formula_explanation_qa":
        if sample.equivalent_coverage_by_k.get(top_k, 0.0) < 1.0:
            reasons.append("formula_context_missing")
        if not _sample_has_formula_graph_expansion(sample):
            reasons.append("graph_expansion_missing")
    if metadata.get("formula_sparse_enabled") and not _sample_has_formula_sparse_hit(sample):
        reasons.append("symbol_sparse_miss")
    if _sample_has_label_question(sample) and not _sample_has_label_match(sample):
        reasons.append("equation_label_miss")
    return _unique_texts(reasons or ["formula_retrieval_low"])


def _formula_failure_suggested_action(reasons: list[str]) -> str:
    if "formula_intent_mismatch" in reasons:
        return "improve_formula_query_routing"
    if "formula_sparse_disabled" in reasons or "symbol_sparse_miss" in reasons:
        return "improve_formula_sparse_scoring"
    if "equation_label_miss" in reasons:
        return "fix_formula_label_metadata"
    if "graph_expansion_missing" in reasons or "formula_context_missing" in reasons:
        return "add_formula_explanation_edge"
    if "missing_gold_in_retrieval" in reasons:
        return "improve_retrieval_policy"
    if "reranker_demoted_gold" in reasons:
        return "tune_formula_reranking"
    return "manual_review_required"


def _sample_has_formula_sparse_hit(sample: EvidenceSampleResult) -> bool:
    for breakdown in sample.ranked_score_breakdowns:
        if float(breakdown.get("formula_sparse_score") or 0.0) > 0.0:
            return True
    return False


def _sample_has_label_match(sample: EvidenceSampleResult) -> bool:
    for breakdown in sample.ranked_score_breakdowns:
        if float(breakdown.get("element_label_score") or 0.0) > 0.0:
            return True
        if float(breakdown.get("formula_label_score") or 0.0) > 0.0:
            return True
    return False


def _sample_has_label_question(sample: EvidenceSampleResult) -> bool:
    return bool(re.search(r"\b(?:equation|eq\.?|formula)\s+[A-Za-z0-9_.:-]+\b", sample.pair.question, re.IGNORECASE))


def _sample_has_formula_graph_expansion(sample: EvidenceSampleResult) -> bool:
    returned = int(sample.retrieval_metadata.get("formula_context_returned") or 0)
    if returned > 0:
        return True
    for breakdown in sample.ranked_score_breakdowns:
        if float(breakdown.get("graph_score") or 0.0) > 0.0:
            return True
    return False


def _formula_retrieval_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "retrieval_policy",
        "formula_sparse_enabled",
        "formula_sparse_recalled",
        "formula_context_returned",
        "field_search_fields",
        "intent",
        "recall_routes",
    )
    return {key: metadata.get(key) for key in keys if key in metadata}


def _coverage(retrieved: list[str], required: list[str]) -> float:
    required_set = set(_unique_texts(required))
    if not required_set:
        return 0.0
    return len(required_set.intersection(retrieved)) / len(required_set)


def _candidate_coverage(retrieved: list[list[str]], required: list[str]) -> float:
    required_set = set(_unique_texts(required))
    if not required_set:
        return 0.0
    covered: set[str] = set()
    for candidates in retrieved:
        covered.update(required_set.intersection(candidates))
    return len(covered) / len(required_set)


def _locator_coverage(retrieved: list[str], required: list[str]) -> float:
    required_locators = _unique_texts(required)
    if not required_locators:
        return 0.0
    hits = 0
    for locator in required_locators:
        if any(_locator_matches(candidate, locator) for candidate in retrieved):
            hits += 1
    return hits / len(required_locators)


def _candidate_locator_coverage(retrieved: list[list[str]], required: list[str]) -> float:
    required_locators = _unique_texts(required)
    if not required_locators:
        return 0.0
    candidates = [locator for locators in retrieved for locator in locators]
    hits = 0
    for locator in required_locators:
        if any(_locator_matches(candidate, locator) for candidate in candidates):
            hits += 1
    return hits / len(required_locators)


def _locator_matches(candidate: str, required: str) -> bool:
    if not candidate or not required:
        return False
    return candidate == required or candidate.startswith(required) or required.startswith(candidate)


def _first_gold_rank(ranked_ids: list[list[str]], gold_ids: list[str]) -> int:
    gold = set(gold_ids)
    for index, chunk_ids in enumerate(ranked_ids, start=1):
        if gold.intersection(chunk_ids):
            return index
    return 0


def _over_retrieval_count(retrieved: list[str], gold_ids: list[str]) -> int:
    gold = set(gold_ids)
    return sum(1 for chunk_id in retrieved if chunk_id not in gold)


def _candidate_over_retrieval_count(retrieved: list[list[str]], gold_ids: list[str]) -> int:
    gold = set(gold_ids)
    return sum(1 for chunk_ids in retrieved if not gold.intersection(chunk_ids))


def _related_context_ids(chunk: PaperChunk) -> list[str]:
    related: list[str] = []
    nearby = str(chunk.metadata.get("nearby_context_chunk_id") or "")
    if nearby:
        related.append(nearby)
    for ref in chunk.metadata.get("referenced_by_chunks", []):
        if isinstance(ref, dict):
            chunk_id = str(ref.get("chunk_id") or "")
            if chunk_id:
                related.append(chunk_id)
    parent_table = str(chunk.metadata.get("parent_table_chunk_id") or "")
    if parent_table:
        related.append(parent_table)
    return _unique_texts(related)


def _referenced_context_chunks(chunk: PaperChunk, chunks_by_id: dict[str, PaperChunk]) -> list[PaperChunk]:
    out: list[PaperChunk] = []
    for ref in chunk.metadata.get("referenced_by_chunks", []):
        if not isinstance(ref, dict):
            continue
        chunk_id = str(ref.get("chunk_id") or "")
        context = chunks_by_id.get(chunk_id)
        if context is not None:
            out.append(context)
    if chunk.parent_chunk_id:
        parent = chunks_by_id.get(chunk.parent_chunk_id)
        if parent is not None:
            out.append(parent)
    return _ranked_unique_chunks(out)


def _explicit_result_reference_chunks(chunk: PaperChunk, chunks_by_id: dict[str, PaperChunk]) -> list[PaperChunk]:
    out: list[PaperChunk] = []
    for ref in chunk.metadata.get("referenced_by_chunks", []):
        if not isinstance(ref, dict):
            continue
        chunk_id = str(ref.get("chunk_id") or "")
        context = chunks_by_id.get(chunk_id)
        if (
            context is not None
            and _is_contentful_related_context_chunk(context)
            and _is_result_context_chunk(context)
        ):
            out.append(context)
    return _ranked_unique_chunks(out)


def _answer_facts_from_chunk(chunk: PaperChunk) -> list[str]:
    caption = _trusted_caption_for_chunk(chunk)
    if chunk.chunk_type == "figure" or chunk.has_figure:
        return _unique_texts([caption]) if caption else [_snippet_from_content(_table_body_without_nearby_context(chunk.content))]
    if chunk.chunk_type == "table" or chunk.has_table:
        table_body = _table_body_without_nearby_context(chunk.content)
        return _unique_texts([
            caption,
            _snippet_from_content(table_body),
        ])[:2]
    candidates = [
        caption,
        _snippet_from_content(chunk.content),
    ]
    return _unique_texts([candidate for candidate in candidates if candidate])[:2]


def _is_result_context_chunk(chunk: PaperChunk) -> bool:
    if chunk.chunk_type != "paragraph":
        return False
    roles = {str(role).casefold() for role in chunk.section_role}
    if roles & {"experiment", "analysis", "conclusion"}:
        return True
    text = f"{chunk.section_title}\n{chunk.content[:400]}".casefold()
    return any(
        keyword in text
        for keyword in (
            "result",
            "results",
            "experiment",
            "evaluation",
            "analysis",
            "conclusion",
            "benchmark",
            "accuracy",
            "score",
            "fid",
            "bleu",
            "f1",
        )
    )


def _is_contentful_related_context_chunk(chunk: PaperChunk) -> bool:
    if chunk.chunk_type != "paragraph":
        return True
    snippet = _clean_citation_claim(_snippet_from_content(chunk.content, max_chars=260))
    if not snippet:
        return False
    lowered = snippet.casefold()
    if re.fullmatch(r"(?:sec|subsec|section|appendix)[:._-]?[a-z0-9_-]*", lowered):
        return False
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]*", snippet)
    meaningful = [
        word for word in words
        if len(word) > 2 and word.casefold() not in {"sec", "subsec", "section", "figure", "table"}
    ]
    return len(meaningful) >= 3


def _is_experiment_result_table(chunk: PaperChunk) -> bool:
    if _evidence_type_for_chunk(chunk) != "table":
        return False
    if _table_content_is_fragmented(chunk):
        return False
    roles = {str(role).casefold() for role in chunk.section_role}
    if roles & {"experiment", "analysis"}:
        role_score = 1
    elif roles & {"conclusion"}:
        role_score = 0
    else:
        role_score = 0
    text = _table_quality_text(chunk)
    lowered = text.casefold()
    negative_hits = _keyword_hits(lowered, _NON_RESULT_TABLE_TOKENS)
    positive_hits = _keyword_hits(lowered, _RESULT_TABLE_TOKENS)
    metric_hits = _keyword_hits(lowered, _RESULT_METRIC_TOKENS)
    comparison_hit = bool(re.search(r"\b(vs\.?|versus|compare[sd]?|comparison|baseline|sota|state-of-the-art)\b", lowered))
    semantic_score = positive_hits + metric_hits + int(comparison_hit)
    result_score = semantic_score + role_score
    if semantic_score <= 0:
        return False
    if negative_hits and semantic_score < 2:
        return False
    return True


def _table_content_is_fragmented(chunk: PaperChunk) -> bool:
    text = " ".join([
        str(chunk.metadata.get("table_text") or ""),
        str(chunk.metadata.get("semantic_text") or ""),
        _table_body_without_nearby_context(chunk.content),
    ])
    columns_match = re.search(r"\bColumns\s*:\s*(.*?)(?:\bRows\s*:|$)", text, flags=re.IGNORECASE | re.DOTALL)
    if not columns_match:
        return False
    columns = [
        column.strip()
        for column in re.split(r"\s*\|\s*|,\s*", columns_match.group(1))
        if column.strip()
    ]
    if len(columns) < 8:
        return False
    fragmented = [
        column
        for column in columns
        if re.fullmatch(r"(?:[A-Za-z](?:_\d+)?|column_\d+|\.)", column, flags=re.IGNORECASE)
    ]
    return len(fragmented) / len(columns) >= 0.5


def _keyword_hits(text: str, keywords: tuple[str, ...]) -> int:
    return sum(1 for keyword in keywords if _keyword_in_text(text, keyword))


def _keyword_in_text(text: str, keyword: str) -> bool:
    token = keyword.casefold().strip()
    if not token:
        return False
    if len(token) <= 3 and re.fullmatch(r"[a-z0-9]+", token):
        return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", text) is not None
    return token in text


def _table_quality_text(chunk: PaperChunk) -> str:
    parts = [
        _trusted_caption_for_chunk(chunk),
        str(chunk.metadata.get("semantic_text") or ""),
        str(chunk.metadata.get("table_text") or ""),
        _caption_from_content(chunk.content),
        _table_body_without_nearby_context(chunk.content),
    ]
    return " ".join(part for part in parts if part)


def _table_body_without_nearby_context(content: str) -> str:
    text = str(content or "")
    if not text.strip():
        return ""
    return re.split(r"\bNearby Context\s*:", text, maxsplit=1, flags=re.IGNORECASE)[0]


def _experiment_table_topic(chunk: PaperChunk) -> str:
    topic = _caption_from_content(chunk.content)
    if not topic:
        topic = _trusted_caption_for_chunk(chunk)
    topic = " ".join(topic.split())
    if len(topic) > 140:
        topic = topic[:140].rsplit(" ", 1)[0].strip()
    return topic


_RESULT_TABLE_TOKENS = (
    "result",
    "results",
    "evaluation",
    "benchmark",
    "performance",
    "accuracy",
    "score",
    "error",
    "loss",
    "metric",
    "ablation",
    "leaderboard",
)


_RESULT_METRIC_TOKENS = (
    "bleu",
    "rouge",
    "f1",
    "em",
    "map",
    "auc",
    "mrr",
    "ndcg",
    "fid",
    "wer",
    "perplexity",
    "ppl",
    "superglue",
    "glue",
    "gsm8k",
)


_NON_RESULT_TABLE_TOKENS = (
    "architecture detail",
    "model architecture",
    "hyperparameter",
    "training dataset",
    "data source",
    "data from each source",
    "proportion of data",
    "amount of code tokens",
    "statistics of",
    "dataset statistics",
)


def _caption_from_content(content: str) -> str:
    lines = [line.strip() for line in content.splitlines()]
    for index, line in enumerate(lines):
        if line.casefold().startswith("caption"):
            suffix = line.split(":", 1)[1].strip() if ":" in line else ""
            if suffix:
                return suffix
            for next_line in lines[index + 1:]:
                if next_line:
                    return next_line
    return ""


def _snippet_from_content(content: str, *, max_chars: int = 180) -> str:
    text = " ".join(str(content or "").split())
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0].strip() or text[:max_chars].strip()


def _clean_citation_claim(snippet: str) -> str:
    text = " ".join(str(snippet or "").split())
    return re.sub(
        r"^(?:sec|subsec|section|appendix)[:._-]?[A-Za-z0-9_-]+\s+",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()


def _is_contentful_citation_claim(snippet: str) -> bool:
    text = str(snippet or "").strip()
    if not text:
        return False
    lowered = text.casefold()
    if re.fullmatch(r"(?:sec|subsec|section|appendix)[:._-]?[a-z0-9_-]*", lowered):
        return False
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]*", text)
    meaningful = [
        word for word in words
        if len(word) > 2 and word.casefold() not in {"sec", "subsec", "section", "figure", "table"}
    ]
    return len(meaningful) >= 6


def _element_label(chunk: PaperChunk, *, fallback: str) -> str:
    for key in ("reference_labels", "table_id", "figure_id", "equation_id"):
        value = chunk.metadata.get(key)
        if isinstance(value, list) and value:
            return str(value[0])
        if value:
            return str(value)
    if chunk.figure_id:
        return chunk.figure_id
    return fallback


def _visual_evidence_coverage(retrieved: list[PaperChunk], gold_image_refs: list[str]) -> float:
    required_images = _unique_texts(gold_image_refs)
    if not required_images:
        return 0.0
    retrieved_images = [_image_ref_candidates_for_chunk(chunk) for chunk in retrieved]
    return _candidate_coverage(retrieved_images, required_images)


def _citation_accuracy(
    retrieved: list[PaperChunk],
    expected_spans: list[dict[str, Any]],
    *,
    span_kind: str | None = None,
) -> float | None:
    spans = [
        span for span in expected_spans
        if span_kind is None or str(span.get("span_kind") or "") == span_kind
    ]
    if not spans:
        return None
    chunks_by_id = {chunk.chunk_id: chunk for chunk in retrieved}
    hits = 0
    for span in spans:
        chunk = _citation_candidate_chunk(span, chunks_by_id)
        if chunk is None:
            continue
        resolved = resolve_citation_span(
            chunk,
            span_start=_optional_int(span.get("span_start")),
            span_end=_optional_int(span.get("span_end")),
            snippet=str(span.get("snippet") or "") or None,
        )
        if _resolved_citation_matches(resolved, span):
            hits += 1
    return hits / len(spans)


def _citation_candidate_chunk(
    span: dict[str, Any],
    chunks_by_id: dict[str, PaperChunk],
) -> PaperChunk | None:
    for key in ("chunk_id", "source_chunk_id", "retrieved_chunk_id"):
        chunk_id = str(span.get(key) or "")
        if chunk_id and chunk_id in chunks_by_id:
            return chunks_by_id[chunk_id]
    return None


def _resolved_citation_matches(resolved: dict[str, Any], expected: dict[str, Any]) -> bool:
    expected_kind = str(expected.get("span_kind") or "")
    if expected_kind and str(resolved.get("span_kind") or "") != expected_kind:
        return False
    expected_chunk_id = str(expected.get("resolved_chunk_id") or expected.get("chunk_id") or "")
    if expected_chunk_id and str(resolved.get("resolved_chunk_id") or "") != expected_chunk_id:
        return False
    expected_locator = str(
        expected.get("resolved_source_locator")
        or expected.get("source_locator")
        or ""
    )
    if expected_locator:
        resolved_locator = str(resolved.get("resolved_source_locator") or "")
        return _locator_matches(resolved_locator, expected_locator)
    return True


def _ranked_unique_chunks(chunks: list[PaperChunk]) -> list[PaperChunk]:
    return dedupe_by_key(chunks, key=lambda chunk: chunk.chunk_id)


def _source_locator_for_chunk(chunk: PaperChunk) -> str:
    return str(chunk.metadata.get("source_locator") or chunk.metadata.get("source_ref") or "")


def _image_ref_for_chunk(chunk: PaperChunk) -> str:
    return str(chunk.metadata.get("image_ref") or "")


def _chunk_match_ids(chunk: PaperChunk) -> list[str]:
    return _unique_texts([
        chunk.chunk_id,
        *_metadata_text_list(chunk.metadata.get("source_chunk_ids")),
        *_metadata_text_list(chunk.metadata.get("covered_chunk_ids")),
    ])


def _evidence_type_candidates_for_chunk(chunk: PaperChunk) -> list[str]:
    return _unique_texts([
        _evidence_type_for_chunk(chunk),
        *_metadata_text_list(chunk.metadata.get("source_evidence_types")),
    ])


def _source_locator_candidates_for_chunk(chunk: PaperChunk) -> list[str]:
    return _unique_texts([
        _source_locator_for_chunk(chunk),
        *_metadata_text_list(chunk.metadata.get("source_locators")),
    ])


def _image_ref_candidates_for_chunk(chunk: PaperChunk) -> list[str]:
    return _unique_texts([
        _image_ref_for_chunk(chunk),
        *_metadata_text_list(chunk.metadata.get("source_image_refs")),
    ])


def _metadata_text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item or "").strip()]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item or "").strip()]
    if isinstance(value, str) and value.strip():
        return [value]
    return []


def _evidence_type_for_chunk(chunk: PaperChunk) -> str:
    if chunk.chunk_type == "formula" or chunk.has_formula:
        return "formula"
    if chunk.chunk_type == "figure" or chunk.has_figure:
        return "figure"
    if chunk.chunk_type == "table" or chunk.has_table:
        return "table"
    return chunk.chunk_type


def _support_context_evidence_type(chunk: PaperChunk) -> str:
    if chunk.chunk_type == "paragraph":
        return "paragraph"
    return _evidence_type_for_chunk(chunk)


def _qa_type_for_chunk(chunk: PaperChunk) -> str:
    if chunk.chunk_type == "formula":
        return "formula_qa"
    if chunk.chunk_type == "figure":
        return "figure_qa"
    if chunk.chunk_type == "table":
        return "table_qa"
    return "citation_qa" if _source_locator_for_chunk(chunk) else "paragraph_qa"


def _coerce_behavior(value: Any) -> EvidenceBehavior:
    behavior = str(value or _ANSWER_BEHAVIOR).strip().lower()
    if behavior not in {_ANSWER_BEHAVIOR, _ABSTAIN_BEHAVIOR}:
        raise ValueError(f"unsupported evidence QA expected_behavior: {value!r}")
    return behavior  # type: ignore[return-value]


def _normalize_citation_spans(values: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        span = {
            str(key): item
            for key, item in value.items()
            if item is not None and str(item).strip()
        }
        if span:
            out.append(span)
    return out


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _require_text(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _unique_texts(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        out.append(text)
        seen.add(text)
    return out


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


__all__ = [
    "EvidenceEvalResult",
    "EvidenceGoldenSetBuilder",
    "EvidenceQAPair",
    "EvidenceRetrievalEvaluator",
    "EvidenceSampleResult",
    "build_evidence_pairs_from_chunks",
    "formula_failure_diagnostics",
    "iter_ranked_score_breakdowns",
    "load_evidence_golden_set",
    "save_evidence_golden_set",
]
