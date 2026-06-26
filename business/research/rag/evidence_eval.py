from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from business.research.document.citation_spans import resolve_citation_span
from business.research.document.models import PaperChunk
from business.research.rag.retriever import ResearchRetriever, RetrievalRequest

EvidenceBehavior = Literal["answer", "abstain"]


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
        return cls(
            question=str(data["question"]),
            paper_id=str(data["paper_id"]),
            qa_type=str(data["qa_type"]),
            gold_chunk_ids=list(data.get("gold_chunk_ids") or []),
            required_evidence_types=list(data.get("required_evidence_types") or []),
            gold_source_locators=list(data.get("gold_source_locators") or []),
            gold_citation_spans=list(data.get("gold_citation_spans") or []),
            gold_image_refs=list(data.get("gold_image_refs") or []),
            answer_facts=list(data.get("answer_facts") or []),
            expected_behavior=_coerce_behavior(data.get("expected_behavior", _ANSWER_BEHAVIOR)),
            difficulty=str(data.get("difficulty") or ""),
            domain=str(data.get("domain") or ""),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class EvidenceSampleResult:
    pair: EvidenceQAPair
    ranked_chunk_ids: list[str]
    ranked_evidence_types: list[str]
    ranked_source_locators: list[str]
    ranked_image_refs: list[str]
    first_rank: int = 0
    coverage_by_k: dict[int, float] = field(default_factory=dict)
    type_coverage_by_k: dict[int, float] = field(default_factory=dict)
    source_locator_coverage_by_k: dict[int, float] = field(default_factory=dict)
    image_recall_by_k: dict[int, float] = field(default_factory=dict)
    visual_evidence_coverage_by_k: dict[int, float] = field(default_factory=dict)
    citation_accuracy_by_k: dict[int, float | None] = field(default_factory=dict)
    overlap_citation_accuracy_by_k: dict[int, float | None] = field(default_factory=dict)
    over_retrieval_by_k: dict[int, int] = field(default_factory=dict)

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
    evidence_coverage_at: dict[int, list[float]] = field(default_factory=dict)
    required_type_coverage_at: dict[int, list[float]] = field(default_factory=dict)
    source_locator_coverage_at: dict[int, list[float]] = field(default_factory=dict)
    image_recall_at: dict[int, list[float]] = field(default_factory=dict)
    visual_evidence_coverage_at: dict[int, list[float]] = field(default_factory=dict)
    citation_accuracy_at: dict[int, list[float]] = field(default_factory=dict)
    overlap_citation_accuracy_at: dict[int, list[float]] = field(default_factory=dict)
    over_retrieval_at: dict[int, list[int]] = field(default_factory=dict)
    reciprocal_ranks: list[float] = field(default_factory=list)
    ndcg_at: dict[int, list[float]] = field(default_factory=dict)
    by_qa_type: dict[str, "EvidenceEvalResult"] = field(default_factory=dict)
    samples: list[EvidenceSampleResult] = field(default_factory=list)

    def hit_rate(self, k: int) -> float:
        return self.hit_at.get(k, 0) / self.answerable_total if self.answerable_total else 0.0

    def evidence_coverage(self, k: int) -> float:
        return _average(self.evidence_coverage_at.get(k, []))

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
                f"EvidenceCoverage@{k:<2} = {self.evidence_coverage(k):.3f}    "
                f"TypeCoverage@{k:<2} = {self.required_type_coverage(k):.3f}    "
                f"SourceLocatorCoverage@{k:<2} = {self.source_locator_coverage(k):.3f}    "
                f"ImageRecall@{k:<2} = {self.image_recall(k):.3f}    "
                f"CitationAccuracy@{k:<2} = {self.citation_accuracy(k):.3f}"
            )
        lines.append(f"  MRR     = {self.mrr():.3f}")
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
                ranked_evidence_types=[],
                ranked_source_locators=[],
                ranked_image_refs=[],
                first_rank=0,
                coverage_by_k={k: 0.0 for k in ks},
                type_coverage_by_k={k: 0.0 for k in ks},
                source_locator_coverage_by_k={k: 0.0 for k in ks},
                image_recall_by_k={k: 0.0 for k in ks},
                visual_evidence_coverage_by_k={k: 0.0 for k in ks},
                citation_accuracy_by_k={k: None for k in ks},
                overlap_citation_accuracy_by_k={k: None for k in ks},
                over_retrieval_by_k={k: 0 for k in ks},
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
        ranked_types = [_evidence_type_for_chunk(chunk) for chunk in ranked_chunks]
        ranked_locators = [_source_locator_for_chunk(chunk) for chunk in ranked_chunks]
        ranked_images = [_image_ref_for_chunk(chunk) for chunk in ranked_chunks]
        first_rank = _first_gold_rank(ranked_ids, pair.gold_chunk_ids)
        return EvidenceSampleResult(
            pair=pair,
            ranked_chunk_ids=ranked_ids,
            ranked_evidence_types=ranked_types,
            ranked_source_locators=ranked_locators,
            ranked_image_refs=ranked_images,
            first_rank=first_rank,
            coverage_by_k={
                k: _coverage(ranked_ids[:k], pair.gold_chunk_ids)
                for k in ks
            },
            type_coverage_by_k={
                k: _coverage(ranked_types[:k], pair.required_evidence_types)
                for k in ks
            },
            source_locator_coverage_by_k={
                k: _locator_coverage(ranked_locators[:k], pair.gold_source_locators)
                for k in ks
            },
            image_recall_by_k={
                k: _coverage(ranked_images[:k], pair.gold_image_refs)
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
                k: _over_retrieval_count(ranked_ids[:k], pair.gold_chunk_ids)
                for k in ks
            },
        )


class EvidenceGoldenSetBuilder:
    """Builds typed evidence QA pairs from parsed paper chunks."""

    def __init__(
        self,
        *,
        max_pairs_per_type: int = _DEFAULT_MAX_PAIRS_PER_TYPE,
        include_negative: bool = True,
    ) -> None:
        self._max_pairs_per_type = max(1, int(max_pairs_per_type))
        self._include_negative = include_negative

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
        return pairs

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
            if len(out) >= self._max_pairs_per_type:
                break
            if _qa_type_for_chunk(chunk) != qa_type:
                continue
            pair = _template_pair_for_chunk(chunk, qa_type, domain=domain, chunks_by_id=chunks_by_id or {})
            if pair is not None:
                out.append(pair)
        return out

    def _build_experiment_result_pairs(
        self,
        chunks: list[PaperChunk],
        *,
        domain: str,
        chunks_by_id: dict[str, PaperChunk],
    ) -> list[EvidenceQAPair]:
        out: list[EvidenceQAPair] = []
        for chunk in chunks:
            if len(out) >= self._max_pairs_per_type:
                break
            if _evidence_type_for_chunk(chunk) != "table":
                continue
            pair = _experiment_result_pair(chunk, domain=domain, chunks_by_id=chunks_by_id)
            if pair is not None:
                out.append(pair)
        return out

    def _build_formula_explanation_pairs(
        self,
        chunks: list[PaperChunk],
        *,
        domain: str,
        chunks_by_id: dict[str, PaperChunk],
    ) -> list[EvidenceQAPair]:
        out: list[EvidenceQAPair] = []
        for chunk in chunks:
            if len(out) >= self._max_pairs_per_type:
                break
            if _evidence_type_for_chunk(chunk) != "formula":
                continue
            pair = _formula_explanation_pair(chunk, domain=domain, chunks_by_id=chunks_by_id)
            if pair is not None:
                out.append(pair)
        return out


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
    return pairs


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
            *(_evidence_type_for_chunk(context) for context in context_chunks),
        ]),
        gold_source_locators=_unique_texts([
            _source_locator_for_chunk(chunk),
            *(_source_locator_for_chunk(context) for context in context_chunks),
        ]),
        answer_facts=_unique_texts([
            *_answer_facts_from_chunk(chunk),
            *(_snippet_from_content(context.content) for context in context_chunks[:2]),
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


def _visual_or_table_pair(
    chunk: PaperChunk,
    *,
    qa_type: str,
    domain: str,
    chunks_by_id: dict[str, PaperChunk],
) -> EvidenceQAPair:
    is_table = qa_type == "table_qa"
    label = _element_label(chunk, fallback="the table" if is_table else "the figure")
    question = (
        f"What do the experimental results around {label} show?"
        if is_table
        else f"What does {label} show?"
    )
    gold_ids = [chunk.chunk_id]
    required_types = ["table" if is_table else "figure"]
    for related_id in _related_context_ids(chunk):
        related = chunks_by_id.get(related_id)
        if related is None:
            continue
        gold_ids.append(related.chunk_id)
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
        answer_facts=_answer_facts_from_chunk(chunk),
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
    context_ids = _related_context_ids(chunk)
    context_chunks = [
        chunks_by_id[chunk_id]
        for chunk_id in context_ids
        if chunk_id in chunks_by_id and _is_result_context_chunk(chunks_by_id[chunk_id])
    ]
    if not context_chunks:
        return None
    label = _element_label(chunk, fallback="the table")
    gold_ids = _unique_texts([chunk.chunk_id, *(context.chunk_id for context in context_chunks)])
    required_types = _unique_texts(["table", *(_evidence_type_for_chunk(context) for context in context_chunks)])
    return EvidenceQAPair(
        question=f"What do the experiment results around {label} show overall?",
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
        },
    )


def _citation_pair(chunk: PaperChunk, *, domain: str) -> EvidenceQAPair | None:
    source_locator = _source_locator_for_chunk(chunk)
    if not source_locator:
        return None
    snippet = _snippet_from_content(chunk.content)
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
        evidence_coverage_at={k: [] for k in ks},
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
    for sample in answerable:
        result.reciprocal_ranks.append(1.0 / sample.first_rank if sample.first_rank else 0.0)
        for k in ks:
            hit = bool(sample.first_rank and sample.first_rank <= k)
            if hit:
                result.hit_at[k] += 1
            result.evidence_coverage_at[k].append(sample.coverage_by_k[k])
            result.required_type_coverage_at[k].append(sample.type_coverage_by_k[k])
            result.source_locator_coverage_at[k].append(sample.source_locator_coverage_by_k[k])
            result.image_recall_at[k].append(sample.image_recall_by_k[k])
            result.visual_evidence_coverage_at[k].append(sample.visual_evidence_coverage_by_k[k])
            citation_accuracy = sample.citation_accuracy_by_k.get(k)
            if citation_accuracy is not None:
                result.citation_accuracy_at[k].append(citation_accuracy)
            overlap_accuracy = sample.overlap_citation_accuracy_by_k.get(k)
            if overlap_accuracy is not None:
                result.overlap_citation_accuracy_at[k].append(overlap_accuracy)
            result.over_retrieval_at[k].append(sample.over_retrieval_by_k[k])
            result.ndcg_at[k].append(_multi_gold_ndcg(sample.ranked_chunk_ids[:k], sample.pair.gold_chunk_ids))
    return result


def _coverage(retrieved: list[str], required: list[str]) -> float:
    required_set = set(_unique_texts(required))
    if not required_set:
        return 0.0
    return len(required_set.intersection(retrieved)) / len(required_set)


def _locator_coverage(retrieved: list[str], required: list[str]) -> float:
    required_locators = _unique_texts(required)
    if not required_locators:
        return 0.0
    hits = 0
    for locator in required_locators:
        if any(_locator_matches(candidate, locator) for candidate in retrieved):
            hits += 1
    return hits / len(required_locators)


def _locator_matches(candidate: str, required: str) -> bool:
    if not candidate or not required:
        return False
    return candidate == required or candidate.startswith(required) or required.startswith(candidate)


def _first_gold_rank(ranked_ids: list[str], gold_ids: list[str]) -> int:
    gold = set(gold_ids)
    for index, chunk_id in enumerate(ranked_ids, start=1):
        if chunk_id in gold:
            return index
    return 0


def _multi_gold_ndcg(ranked_ids: list[str], gold_ids: list[str]) -> float:
    gold = set(gold_ids)
    if not gold:
        return 0.0
    dcg = 0.0
    for index, chunk_id in enumerate(ranked_ids, start=1):
        if chunk_id in gold:
            dcg += 1.0 / math.log2(index + 1)
    ideal_hits = min(len(gold), len(ranked_ids))
    ideal = sum(1.0 / math.log2(index + 1) for index in range(1, ideal_hits + 1))
    return dcg / ideal if ideal else 0.0


def _over_retrieval_count(retrieved: list[str], gold_ids: list[str]) -> int:
    gold = set(gold_ids)
    return sum(1 for chunk_id in retrieved if chunk_id not in gold)


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


def _answer_facts_from_chunk(chunk: PaperChunk) -> list[str]:
    candidates = [
        str(chunk.metadata.get("caption_text") or ""),
        str(chunk.metadata.get("surya_caption") or ""),
        _caption_from_content(chunk.content),
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
    retrieved_images = [_image_ref_for_chunk(chunk) for chunk in retrieved]
    return _coverage(retrieved_images, required_images)


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
    seen: set[str] = set()
    out: list[PaperChunk] = []
    for chunk in chunks:
        if chunk.chunk_id in seen:
            continue
        out.append(chunk)
        seen.add(chunk.chunk_id)
    return out


def _source_locator_for_chunk(chunk: PaperChunk) -> str:
    return str(chunk.metadata.get("source_locator") or chunk.metadata.get("source_ref") or "")


def _image_ref_for_chunk(chunk: PaperChunk) -> str:
    return str(chunk.metadata.get("image_ref") or "")


def _evidence_type_for_chunk(chunk: PaperChunk) -> str:
    if chunk.chunk_type == "formula" or chunk.has_formula:
        return "formula"
    if chunk.chunk_type == "figure" or chunk.has_figure:
        return "figure"
    if chunk.chunk_type == "table" or chunk.has_table:
        return "table"
    return chunk.chunk_type


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
    "load_evidence_golden_set",
    "save_evidence_golden_set",
]
