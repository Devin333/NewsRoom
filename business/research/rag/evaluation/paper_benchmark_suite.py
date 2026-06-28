from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol, Sequence

from business.research.document.models import PaperChunk
from business.research.application.llm_client import _browser_ua_transport
from business.research.rag.adapters.paper_chunk_adapter import paper_chunk_to_rag_evidence
from business.research.rag.evaluation.paper_answer_eval import EvidenceAnswerEvaluator, EvidenceAnswerSample
from business.research.rag.evaluation.paper_evidence_eval import (
    EvidenceGoldenSetBuilder,
    EvidenceQAPair,
    EvidenceRetrievalEvaluator,
    save_evidence_golden_set,
)
from business.research.rag.evaluation.paper_evaluation_report import EvidenceRegressionReport
from business.research.rag.evaluation.paper_fixed_window_baseline import FixedWindowBaselineChunker, FixedWindowChunkerConfig
from business.research.rag.evaluation.paper_generation_eval import GenerationEvaluator, GenerationEvalResult
from business.research.rag.retrieval.paper_answer_generator import AnswerGenerator, GeneratedAnswer
from business.research.rag.visual.page_visual_chunks import build_page_visual_chunks
from business.research.rag.cli.run_evidence_eval import _build_live_retriever, _load_chunks_from_papers_dir
from business.research.rag.retrieval.paper_retriever import RetrievalRequest
from framework.llm.clients.openai_compatible import LLMRetryPolicy, OpenAICompatibleClient, OpenAICompatibleConfig
from framework.llm.models.request import LLMRequest
from framework.shared.env import load_root_env

LLMCall = Callable[[str], Awaitable[str]]

DEFAULT_SPLIT_RATIOS = (0.6, 0.2, 0.2)
DEFAULT_TARGET_QA_TYPES = (
    "citation_qa",
    "experiment_result_qa",
    "figure_qa",
    "formula_explanation_qa",
    "formula_qa",
    "table_qa",
)


@dataclass(frozen=True)
class BenchmarkSplit:
    name: str
    paper_ids: tuple[str, ...]
    pair_count: int
    qa_type_counts: dict[str, int]


@dataclass(frozen=True)
class GoldEvidenceAuditItem:
    question: str
    paper_id: str
    qa_type: str
    status: str
    reason: str
    gold_chunk_ids: tuple[str, ...] = ()
    missing_chunk_ids: tuple[str, ...] = ()
    answer_facts_present: bool = False
    source_locator_count: int = 0
    image_ref_count: int = 0
    answer_facts: tuple[str, ...] = ()
    evidence_previews: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "paper_id": self.paper_id,
            "qa_type": self.qa_type,
            "status": self.status,
            "reason": self.reason,
            "gold_chunk_ids": list(self.gold_chunk_ids),
            "missing_chunk_ids": list(self.missing_chunk_ids),
            "answer_facts_present": self.answer_facts_present,
            "source_locator_count": self.source_locator_count,
            "image_ref_count": self.image_ref_count,
            "answer_facts": list(self.answer_facts),
            "evidence_previews": [dict(item) for item in self.evidence_previews],
        }


@dataclass(frozen=True)
class GoldEvidenceAuditReport:
    sample_size: int
    passed: int
    warning: int
    failed: int
    by_qa_type: dict[str, dict[str, int]] = field(default_factory=dict)
    items: tuple[GoldEvidenceAuditItem, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_size": self.sample_size,
            "passed": self.passed,
            "warning": self.warning,
            "failed": self.failed,
            "by_qa_type": {
                qa_type: dict(counts)
                for qa_type, counts in sorted(self.by_qa_type.items())
            },
            "items": [item.to_dict() for item in self.items],
        }


@dataclass(frozen=True)
class GoldEvidenceJudgeItem:
    question: str
    paper_id: str
    qa_type: str
    status: str
    reason: str
    supported: bool = False
    confidence: float = 0.0
    raw_response: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "paper_id": self.paper_id,
            "qa_type": self.qa_type,
            "status": self.status,
            "reason": self.reason,
            "supported": self.supported,
            "confidence": self.confidence,
            "raw_response": dict(self.raw_response),
        }


@dataclass(frozen=True)
class GoldEvidenceJudgeReport:
    mode: str
    provider: str
    model: str
    sample_size: int
    passed: int
    warning: int
    failed: int
    error: int
    items: tuple[GoldEvidenceJudgeItem, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "provider": self.provider,
            "model": self.model,
            "sample_size": self.sample_size,
            "passed": self.passed,
            "warning": self.warning,
            "failed": self.failed,
            "error": self.error,
            "items": [item.to_dict() for item in self.items],
        }


class GoldEvidenceJudge(Protocol):
    def judge(self, items: Sequence[GoldEvidenceAuditItem]) -> GoldEvidenceJudgeReport:
        ...


@dataclass(frozen=True)
class SpotCheckReport:
    sample_path: str
    sample_size: int
    annotation_path: str = ""
    annotated_count: int = 0
    label_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_path": self.sample_path,
            "sample_size": self.sample_size,
            "annotation_path": self.annotation_path,
            "annotated_count": self.annotated_count,
            "label_counts": dict(sorted(self.label_counts.items())),
        }


@dataclass(frozen=True)
class QuestionAmbiguityAuditItem:
    question: str
    paper_id: str
    qa_type: str
    reasons: tuple[str, ...]
    gold_chunk_ids: tuple[str, ...] = ()
    semantic_anchors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "paper_id": self.paper_id,
            "qa_type": self.qa_type,
            "reasons": list(self.reasons),
            "gold_chunk_ids": list(self.gold_chunk_ids),
            "semantic_anchors": list(self.semantic_anchors),
        }


@dataclass(frozen=True)
class QuestionAmbiguityAuditReport:
    total: int
    duplicate_questions: int
    ambiguous_questions: int
    missing_semantic_anchor: int
    label_leakage: int
    caption_copy: int
    by_qa_type: dict[str, dict[str, int]] = field(default_factory=dict)
    items: tuple[QuestionAmbiguityAuditItem, ...] = ()

    @property
    def duplicate_question_rate(self) -> float:
        return self.duplicate_questions / self.total if self.total else 0.0

    @property
    def ambiguous_question_rate(self) -> float:
        return self.ambiguous_questions / self.total if self.total else 0.0

    @property
    def missing_semantic_anchor_rate(self) -> float:
        return self.missing_semantic_anchor / self.total if self.total else 0.0

    @property
    def label_leakage_rate(self) -> float:
        return self.label_leakage / self.total if self.total else 0.0

    @property
    def caption_copy_rate(self) -> float:
        return self.caption_copy / self.total if self.total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "duplicate_questions": self.duplicate_questions,
            "duplicate_question_rate": self.duplicate_question_rate,
            "ambiguous_questions": self.ambiguous_questions,
            "ambiguous_question_rate": self.ambiguous_question_rate,
            "missing_semantic_anchor": self.missing_semantic_anchor,
            "missing_semantic_anchor_rate": self.missing_semantic_anchor_rate,
            "label_leakage": self.label_leakage,
            "label_leakage_rate": self.label_leakage_rate,
            "caption_copy": self.caption_copy,
            "caption_copy_rate": self.caption_copy_rate,
            "by_qa_type": {
                qa_type: dict(counts)
                for qa_type, counts in sorted(self.by_qa_type.items())
            },
            "items": [item.to_dict() for item in self.items],
        }


class OpenAICompatibleGoldEvidenceJudge:
    """Optional LLM audit for whether gold evidence supports a QA pair."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key_env: str = "OPENAI_API_KEY",
        max_evidence_chars: int = 1600,
        client: OpenAICompatibleClient | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("gold evidence LLM judge requires OPENAI_BASE_URL or NEWS_GOLD_JUDGE_BASE_URL")
        if not os.environ.get(api_key_env):
            raise ValueError(f"gold evidence LLM judge requires {api_key_env}")
        self._model = model
        self._max_evidence_chars = max(200, int(max_evidence_chars))
        self._client = client or OpenAICompatibleClient(
            OpenAICompatibleConfig(
                provider="openai-compatible-gold-judge",
                base_url=base_url.rstrip("/"),
                model=model,
                api_key_env=api_key_env,
                timeout_seconds=90.0,
            ),
            transport=_browser_ua_transport,
            retry_policy=LLMRetryPolicy(max_attempts=2, retry_delay_seconds=(1.0,)),
        )

    @classmethod
    def from_env(cls, *, max_evidence_chars: int = 1600) -> "OpenAICompatibleGoldEvidenceJudge":
        load_root_env()
        base_url = os.environ.get("NEWS_GOLD_JUDGE_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or ""
        model = os.environ.get("NEWS_GOLD_JUDGE_MODEL") or os.environ.get("OPENAI_MODEL") or "gpt-5.4-mini"
        api_key_env = os.environ.get("NEWS_GOLD_JUDGE_API_KEY_ENV") or "OPENAI_API_KEY"
        return cls(
            base_url=base_url,
            model=model,
            api_key_env=api_key_env,
            max_evidence_chars=max_evidence_chars,
        )

    def judge(self, items: Sequence[GoldEvidenceAuditItem]) -> GoldEvidenceJudgeReport:
        judged = tuple(self._judge_one(item) for item in items)
        counts = Counter(item.status for item in judged)
        return GoldEvidenceJudgeReport(
            mode="llm",
            provider="openai-compatible",
            model=self._model,
            sample_size=len(judged),
            passed=counts.get("pass", 0),
            warning=counts.get("warning", 0),
            failed=counts.get("fail", 0),
            error=counts.get("error", 0),
            items=judged,
        )

    def _judge_one(self, item: GoldEvidenceAuditItem) -> GoldEvidenceJudgeItem:
        try:
            response = self._client.complete(LLMRequest(
                messages=[{"role": "user", "content": _judge_prompt(item, self._max_evidence_chars)}],
                max_tokens=300,
                temperature=0,
                response_format={"type": "json_object"},
            ))
            payload = _extract_json_object(response.content or "")
        except Exception as exc:  # noqa: BLE001 - audit must not crash the suite mid-sample
            return GoldEvidenceJudgeItem(
                question=item.question,
                paper_id=item.paper_id,
                qa_type=item.qa_type,
                status="error",
                reason=type(exc).__name__,
            )

        supported = bool(payload.get("supported"))
        confidence = _clamped_float(payload.get("confidence"))
        reason = str(payload.get("reason") or "").strip()[:500] or "no_reason"
        status = "pass" if supported and confidence >= 0.6 else "warning" if supported else "fail"
        return GoldEvidenceJudgeItem(
            question=item.question,
            paper_id=item.paper_id,
            qa_type=item.qa_type,
            status=status,
            reason=reason,
            supported=supported,
            confidence=confidence,
            raw_response=payload,
        )


@dataclass
class BenchmarkSuiteResult:
    output_dir: Path
    papers_total: int
    chunks_total: int
    pairs_total: int
    split_seed: str
    splits: dict[str, BenchmarkSplit]
    target_qa_counts: dict[str, int]
    question_profile: str
    question_audit: QuestionAmbiguityAuditReport
    gold_audit: GoldEvidenceAuditReport
    gold_judge: GoldEvidenceJudgeReport | None
    spot_check: SpotCheckReport | None
    candidate_test_report: dict[str, Any]
    baseline_test_report: dict[str, Any] | None
    ab_report: dict[str, Any] | None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        test_policy = "candidate is evaluated on the test split"
        if self.baseline_test_report is not None:
            test_policy = "candidate and fixed-window baseline are evaluated only on the test split"
        return {
            "output_dir": str(self.output_dir),
            "papers_total": self.papers_total,
            "chunks_total": self.chunks_total,
            "pairs_total": self.pairs_total,
            "split_seed": self.split_seed,
            "splits": {name: _split_to_dict(split) for name, split in self.splits.items()},
            "target_qa_counts": dict(self.target_qa_counts),
            "evaluation_protocol": {
                "train_split": "train",
                "tuning_split": "dev",
                "reported_split": "test",
                "test_policy": test_policy,
                "question_profile": self.question_profile,
                "blind_test": _is_blind_question_profile(self.question_profile),
                "detemplate_policy": _detemplate_policy_for_profile(self.question_profile),
            },
            "question_audit": self.question_audit.to_dict(),
            "gold_audit": self.gold_audit.to_dict(),
            "gold_judge": self.gold_judge.to_dict() if self.gold_judge is not None else None,
            "spot_check": self.spot_check.to_dict() if self.spot_check is not None else None,
            "candidate_test_report": self.candidate_test_report,
            "baseline_test_report": self.baseline_test_report,
            "ab_report": self.ab_report,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class BenchmarkSuiteConfig:
    papers_dir: Path
    output_dir: Path
    image_root: Path | None = None
    retrieval_policy: str = "paper_visual_rag_tuned"
    max_pairs_per_type: int = 100
    min_papers: int = 20
    target_min_per_type: int = 50
    split_seed: str = "paper-rag-benchmark-v1"
    split_ratios: tuple[float, float, float] = DEFAULT_SPLIT_RATIOS
    include_negative: bool = True
    question_profile: str = "template"
    visual: bool = True
    page_visual: bool = True
    render_page_visual: bool = False
    gold_audit_sample_size: int = 30
    gold_judge_mode: str = "none"
    gold_judge_sample_size: int | None = None
    gold_judge_max_evidence_chars: int = 1600
    gold_evidence_judge: GoldEvidenceJudge | None = None
    answer_eval_enabled: bool = False
    answer_eval_sample_size: int | None = None
    answer_max_context_chunks: int = 5
    answer_max_chars_per_chunk: int = 1000
    answer_llm_call: LLMCall | None = None
    answer_judge_mode: str = "none"
    answer_judge_sample_size: int | None = None
    answer_judge_llm_call: LLMCall | None = None
    spot_check_sample_size: int = 0
    spot_check_annotations_path: Path | None = None
    quality_thresholds: dict[str, float] = field(default_factory=dict)
    include_fixed_window_baseline: bool = False
    fixed_window_tokens: int = 220
    fixed_window_overlap_tokens: int | None = None


def run_benchmark_suite(config: BenchmarkSuiteConfig) -> BenchmarkSuiteResult:
    output_dir = config.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    question_profile = _normalize_question_profile(config.question_profile)
    base_chunks, chunks = _load_suite_chunk_sets(config)
    gold_chunks = _gold_builder_chunks(base_chunks)
    paper_ids = sorted({chunk.paper_id for chunk in gold_chunks})
    pairs = EvidenceGoldenSetBuilder(
        max_pairs_per_type=config.max_pairs_per_type,
        include_negative=config.include_negative,
        question_profile=question_profile,
    ).build(gold_chunks)
    question_audit = audit_question_ambiguity(pairs, gold_chunks)
    target_counts = _target_counts(pairs)
    split_map = split_paper_ids(
        paper_ids,
        seed=config.split_seed,
        ratios=config.split_ratios,
    )
    split_pairs = {
        name: [pair for pair in pairs if pair.paper_id in set(ids)]
        for name, ids in split_map.items()
    }
    splits = {
        name: BenchmarkSplit(
            name=name,
            paper_ids=tuple(ids),
            pair_count=len(split_pairs[name]),
            qa_type_counts=dict(sorted(Counter(pair.qa_type for pair in split_pairs[name]).items())),
        )
        for name, ids in split_map.items()
    }

    for name, current_pairs in split_pairs.items():
        split_dir = output_dir / name
        split_dir.mkdir(parents=True, exist_ok=True)
        save_evidence_golden_set(current_pairs, split_dir / "golden_set.json")

    test_pairs = split_pairs.get("test", [])
    audit = audit_gold_evidence(test_pairs, chunks, sample_size=config.gold_audit_sample_size, seed=config.split_seed)
    judge_report = _run_gold_judge(config, audit)
    candidate_report, spot_check = _evaluate_candidate(config, chunks, test_pairs, output_dir / "test" / "candidate")
    baseline_report = None
    ab_report = None
    if config.include_fixed_window_baseline:
        baseline_report = _evaluate_fixed_window_baseline(config, chunks, test_pairs, output_dir / "test" / "fixed_window")
        ab_report = _compare_reports(candidate_report, baseline_report)

    warnings = _suite_warnings(
        paper_count=len(paper_ids),
        target_counts=target_counts,
        config=config,
        splits=splits,
        audit=audit,
        judge_report=judge_report,
        candidate_report=candidate_report,
    )
    result = BenchmarkSuiteResult(
        output_dir=output_dir,
        papers_total=len(paper_ids),
        chunks_total=len(chunks),
        pairs_total=len(pairs),
        split_seed=config.split_seed,
        splits=splits,
        target_qa_counts=target_counts,
        question_profile=question_profile,
        question_audit=question_audit,
        gold_audit=audit,
        gold_judge=judge_report,
        spot_check=spot_check,
        candidate_test_report=candidate_report,
        baseline_test_report=baseline_report,
        ab_report=ab_report,
        warnings=warnings,
    )
    _write_suite_report(result)
    return result


def split_paper_ids(
    paper_ids: Sequence[str],
    *,
    seed: str,
    ratios: tuple[float, float, float] = DEFAULT_SPLIT_RATIOS,
) -> dict[str, list[str]]:
    if len(ratios) != 3:
        raise ValueError("split ratios must contain train/dev/test")
    if any(value < 0 for value in ratios) or sum(ratios) <= 0:
        raise ValueError("split ratios must be non-negative and non-empty")
    ordered = sorted(set(paper_ids), key=lambda paper_id: _stable_split_key(seed, paper_id))
    total = len(ordered)
    if total == 0:
        return {"train": [], "dev": [], "test": []}
    train_count = int(total * ratios[0] / sum(ratios))
    dev_count = int(total * ratios[1] / sum(ratios))
    if total >= 3:
        train_count = max(1, train_count)
        dev_count = max(1, dev_count)
        if train_count + dev_count >= total:
            dev_count = max(1, total - train_count - 1)
    test_count = max(0, total - train_count - dev_count)
    if total >= 3 and test_count == 0:
        test_count = 1
        if dev_count > 1:
            dev_count -= 1
        else:
            train_count = max(1, train_count - 1)
    return {
        "train": ordered[:train_count],
        "dev": ordered[train_count:train_count + dev_count],
        "test": ordered[train_count + dev_count:],
    }


def _normalize_question_profile(profile: str) -> str:
    normalized = str(profile or "template").strip().casefold()
    if normalized in {"", "template"}:
        return "template"
    if normalized in {"blind", "blind_detemplated", "detemplated"}:
        return "blind_detemplated"
    if normalized in {"blind_semantic", "semantic", "semantic_blind"}:
        return "blind_semantic"
    raise ValueError("question_profile must be 'template', 'blind_detemplated', or 'blind_semantic'")


def _is_blind_question_profile(profile: str) -> bool:
    return _normalize_question_profile(profile) != "template"


def _detemplate_policy_for_profile(profile: str) -> str:
    normalized = _normalize_question_profile(profile)
    if normalized == "blind_detemplated":
        return "remove_labels_caption_quote_v1"
    if normalized == "blind_semantic":
        return "semantic_anchors_no_labels_v1"
    return ""


def audit_question_ambiguity(
    pairs: Sequence[EvidenceQAPair],
    chunks: Sequence[PaperChunk],
) -> QuestionAmbiguityAuditReport:
    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    normalized_groups: dict[tuple[str, str, str], list[tuple[int, EvidenceQAPair]]] = {}
    for index, pair in enumerate(pairs):
        key = (pair.paper_id, pair.qa_type, _normalize_question_text(pair.question))
        normalized_groups.setdefault(key, []).append((index, pair))

    duplicate_indexes: set[int] = set()
    ambiguous_indexes: set[int] = set()
    for grouped in normalized_groups.values():
        if len(grouped) <= 1:
            continue
        duplicate_indexes.update(index for index, _pair in grouped)
        gold_signatures = {
            tuple(pair.gold_chunk_ids)
            for _index, pair in grouped
            if pair.expected_behavior == "answer"
        }
        if len(gold_signatures) > 1:
            ambiguous_indexes.update(index for index, _pair in grouped)

    missing_anchor_indexes: set[int] = set()
    label_leakage_indexes: set[int] = set()
    caption_copy_indexes: set[int] = set()
    flagged_items: list[QuestionAmbiguityAuditItem] = []
    by_qa_type: dict[str, Counter[str]] = {}

    for index, pair in enumerate(pairs):
        reasons: list[str] = []
        anchors = tuple(str(anchor) for anchor in pair.metadata.get("semantic_anchors") or [])
        if index in duplicate_indexes:
            reasons.append("duplicate_question")
        if index in ambiguous_indexes:
            reasons.append("ambiguous_question")
        if _missing_semantic_anchor(pair):
            missing_anchor_indexes.add(index)
            reasons.append("missing_semantic_anchor")
        if _question_has_label_leakage(pair.question):
            label_leakage_indexes.add(index)
            reasons.append("label_leakage")
        if _question_copies_source_text(pair, chunks_by_id):
            caption_copy_indexes.add(index)
            reasons.append("caption_copy")

        counts = by_qa_type.setdefault(pair.qa_type, Counter())
        counts["total"] += 1
        for reason in reasons:
            counts[reason] += 1
        if reasons:
            flagged_items.append(QuestionAmbiguityAuditItem(
                question=pair.question,
                paper_id=pair.paper_id,
                qa_type=pair.qa_type,
                reasons=tuple(reasons),
                gold_chunk_ids=tuple(pair.gold_chunk_ids),
                semantic_anchors=anchors,
            ))

    return QuestionAmbiguityAuditReport(
        total=len(pairs),
        duplicate_questions=len(duplicate_indexes),
        ambiguous_questions=len(ambiguous_indexes),
        missing_semantic_anchor=len(missing_anchor_indexes),
        label_leakage=len(label_leakage_indexes),
        caption_copy=len(caption_copy_indexes),
        by_qa_type={qa_type: dict(counter) for qa_type, counter in by_qa_type.items()},
        items=tuple(flagged_items[:100]),
    )


def _normalize_question_text(question: str) -> str:
    return " ".join(str(question or "").casefold().split())


def _missing_semantic_anchor(pair: EvidenceQAPair) -> bool:
    if pair.expected_behavior != "answer":
        return False
    profile = str(pair.metadata.get("question_profile") or "template")
    anchors = [
        str(anchor).strip()
        for anchor in pair.metadata.get("semantic_anchors") or []
        if str(anchor).strip()
    ]
    if _normalize_question_profile(profile) == "blind_semantic":
        return len(anchors) < 2
    return len(_semantic_question_tokens(pair.question)) < 2


def _semantic_question_tokens(question: str) -> list[str]:
    stopwords = {
        "about", "does", "evidence", "explain", "explains", "ground", "grounds", "paper",
        "passage", "question", "reported", "result", "results", "section", "show", "shows",
        "suggest", "table", "figure", "formula", "equation", "what", "which", "where", "with",
        "used", "overall", "quantitative", "visual", "mathematical", "relation",
    }
    out: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", str(question or "")):
        normalized = token.casefold()
        if normalized in stopwords or normalized in seen:
            continue
        out.append(token)
        seen.add(normalized)
    return out


def _question_has_label_leakage(question: str) -> bool:
    text = str(question or "")
    return bool(re.search(
        r"\b(?:figure|fig\.?|table|equation|eq\.?)\s+[A-Za-z0-9_.:-]+\b",
        text,
        flags=re.IGNORECASE,
    ))


def _question_copies_source_text(pair: EvidenceQAPair, chunks_by_id: dict[str, PaperChunk]) -> bool:
    question_tokens = _copy_check_tokens(pair.question)
    if len(question_tokens) < 8:
        return False
    for text in _source_texts_for_copy_audit(pair, chunks_by_id):
        if _longest_common_token_run(question_tokens, _copy_check_tokens(text)) >= 8:
            return True
    return False


def _source_texts_for_copy_audit(pair: EvidenceQAPair, chunks_by_id: dict[str, PaperChunk]) -> list[str]:
    texts: list[str] = []
    texts.extend(pair.answer_facts)
    for chunk_id in pair.gold_chunk_ids:
        chunk = chunks_by_id.get(chunk_id)
        if chunk is None:
            continue
        texts.extend([
            str(chunk.metadata.get("caption_text") or ""),
            str(chunk.metadata.get("surya_caption") or ""),
            str(chunk.metadata.get("visual_description") or ""),
            str(chunk.metadata.get("semantic_text") or ""),
            str(chunk.metadata.get("table_text") or ""),
            _caption_block_for_audit(chunk.content),
        ])
    return [text for text in texts if str(text).strip()]


def _copy_check_tokens(text: str) -> list[str]:
    return [
        token.casefold()
        for token in re.findall(r"[A-Za-z0-9]+", str(text or ""))
        if len(token) > 1
    ]


def _longest_common_token_run(left: list[str], right: list[str]) -> int:
    if not left or not right:
        return 0
    previous = [0] * (len(right) + 1)
    best = 0
    for left_token in left:
        current = [0] * (len(right) + 1)
        for index, right_token in enumerate(right, start=1):
            if left_token != right_token:
                continue
            current[index] = previous[index - 1] + 1
            best = max(best, current[index])
        previous = current
    return best


def _caption_block_for_audit(content: str) -> str:
    marker = "caption:"
    normalized = str(content or "").casefold()
    index = normalized.find(marker)
    if index < 0:
        return ""
    tail = str(content or "")[index + len(marker):]
    lines: list[str] = []
    for line in tail.splitlines():
        stripped = line.strip()
        if not stripped:
            if lines:
                break
            continue
        if stripped.endswith(":") and lines:
            break
        lines.append(stripped)
    return " ".join(lines)


def audit_gold_evidence(
    pairs: Sequence[EvidenceQAPair],
    chunks: Sequence[PaperChunk],
    *,
    sample_size: int,
    seed: str,
) -> GoldEvidenceAuditReport:
    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    sample = _stable_sample(list(pairs), sample_size=max(0, sample_size), seed=seed)
    items = tuple(_audit_pair(pair, chunks_by_id) for pair in sample)
    counts = Counter(item.status for item in items)
    by_qa_type: dict[str, dict[str, int]] = {}
    for qa_type in sorted({item.qa_type for item in items}):
        type_counts = Counter(item.status for item in items if item.qa_type == qa_type)
        by_qa_type[qa_type] = {
            "pass": type_counts.get("pass", 0),
            "warning": type_counts.get("warning", 0),
            "fail": type_counts.get("fail", 0),
        }
    return GoldEvidenceAuditReport(
        sample_size=len(items),
        passed=counts.get("pass", 0),
        warning=counts.get("warning", 0),
        failed=counts.get("fail", 0),
        by_qa_type=by_qa_type,
        items=items,
    )


def _load_suite_chunk_sets(config: BenchmarkSuiteConfig) -> tuple[list[PaperChunk], list[PaperChunk]]:
    base_chunks = _load_chunks_from_papers_dir(config.papers_dir)
    chunks = list(base_chunks)
    if config.page_visual:
        chunks.extend(build_page_visual_chunks(
            chunks,
            papers_dir=config.papers_dir,
            render_pages=config.render_page_visual,
        ))
    return base_chunks, chunks


def _gold_builder_chunks(chunks: Sequence[PaperChunk]) -> list[PaperChunk]:
    return [
        chunk for chunk in chunks
        if not chunk.metadata.get("page_visual") and not chunk.metadata.get("is_parent")
    ]


def _evaluate_candidate(
    config: BenchmarkSuiteConfig,
    chunks: list[PaperChunk],
    pairs: list[EvidenceQAPair],
    output_dir: Path,
) -> tuple[dict[str, Any], SpotCheckReport | None]:
    retriever, visual_store = _build_live_retriever(
        chunks,
        visual_enabled=config.visual,
        image_root=config.image_root or config.papers_dir,
        retrieval_policy=config.retrieval_policy,
    )
    retrieval = EvidenceRetrievalEvaluator(retriever).evaluate(pairs)
    answer_samples: list[EvidenceAnswerSample] = []
    generated_answers: list[GeneratedAnswer] = []
    answer_result = None
    generation_result = None
    if _answers_requested(config):
        answer_samples, generated_answers = asyncio.run(_generate_answer_samples(config, retriever, pairs))
        if config.answer_eval_enabled:
            answer_result = EvidenceAnswerEvaluator().evaluate(answer_samples)
        if _answer_judge_enabled(config):
            judge_answers = _answer_judge_sample(generated_answers, config)
            generation_result = asyncio.run(_run_answer_judge(config, judge_answers))
        _write_answer_samples(
            output_dir / "answer_samples.jsonl",
            answer_samples,
            generated_answers,
            answer_result=answer_result,
        )
    metadata = {
        "mode": "candidate",
        "retrieval_policy": retriever.policy.name,
        "question_profile": _normalize_question_profile(config.question_profile),
        "blind_test": _is_blind_question_profile(config.question_profile),
        "chunks_total": len(chunks),
        "visual_fusion_enabled": visual_store is not None,
        "visual_indexed_chunks": len(getattr(visual_store, "_vectors", {})) if visual_store is not None else 0,
        "answer_eval_enabled": config.answer_eval_enabled,
        "answer_judge_mode": config.answer_judge_mode,
        "answer_samples": len(answer_samples),
    }
    report = EvidenceRegressionReport(
        retrieval=retrieval,
        answer=answer_result,
        generation=generation_result,
        thresholds=dict(config.quality_thresholds),
        metadata=metadata,
    )
    report.write(output_dir)
    payload = json.loads((output_dir / "evidence_regression_report.json").read_text(encoding="utf-8"))
    spot_check = _write_spot_check_report(
        config,
        output_dir=output_dir,
        answer_samples=answer_samples,
        generated_answers=generated_answers,
        answer_result=answer_result,
    )
    if spot_check is not None:
        payload["spot_check"] = spot_check.to_dict()
        (output_dir / "evidence_regression_report.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return payload, spot_check


def _answers_requested(config: BenchmarkSuiteConfig) -> bool:
    return (
        config.answer_eval_enabled
        or _answer_judge_enabled(config)
        or config.spot_check_sample_size > 0
    )


def _answer_judge_enabled(config: BenchmarkSuiteConfig) -> bool:
    mode = str(config.answer_judge_mode or "none").strip().casefold()
    return mode not in {"", "none", "off", "false", "0"}


async def _generate_answer_samples(
    config: BenchmarkSuiteConfig,
    retriever: Any,
    pairs: list[EvidenceQAPair],
) -> tuple[list[EvidenceAnswerSample], list[GeneratedAnswer]]:
    llm_call = config.answer_llm_call or _build_answer_llm_call(max_tokens=700)
    generator = AnswerGenerator(
        llm_call,
        max_context_chunks=config.answer_max_context_chunks,
        max_chars_per_chunk=config.answer_max_chars_per_chunk,
    )
    samples: list[EvidenceAnswerSample] = []
    generated: list[GeneratedAnswer] = []
    for pair in _answer_generation_pairs(pairs, config):
        retrieval = retriever.retrieve(RetrievalRequest(
            paper_id=pair.paper_id,
            question=pair.question,
            limit=10,
        ))
        answer = await generator.generate(
            pair.question,
            retrieval,
            required_context_ids=pair.gold_chunk_ids,
        )
        context_chunks = _context_chunks_for_answer(retrieval, answer.context_chunk_ids)
        context_score_breakdowns = _context_score_breakdowns(context_chunks)
        answer.context_metadata["context_score_breakdowns"] = context_score_breakdowns
        cited_chunk_ids = _cited_chunk_ids(answer.answer, answer.context_chunk_ids)
        context_by_id = {chunk.chunk_id: chunk for chunk in context_chunks}
        cited_locators = [
            locator for chunk_id in cited_chunk_ids
            if (locator := _chunk_source_locator(context_by_id.get(chunk_id)))
        ]
        samples.append(EvidenceAnswerSample(
            pair=pair,
            answer=answer.answer,
            cited_chunk_ids=cited_chunk_ids,
            cited_source_locators=cited_locators,
            context_chunk_ids=list(answer.context_chunk_ids),
            metadata={
                "context_count": len(answer.context_chunk_ids),
                "citation_count": len(cited_chunk_ids),
                "retrieved_chunk_ids": list(answer.context_metadata.get("retrieved_chunk_ids") or []),
                "context_selection_strategy": answer.context_metadata.get("context_selection_strategy", ""),
                "context_source_buckets": dict(answer.context_metadata.get("context_source_buckets") or {}),
                "required_context_ids": list(answer.context_metadata.get("required_context_ids") or []),
                "selected_required_context_ids": list(
                    answer.context_metadata.get("selected_required_context_ids") or []
                ),
                "missing_required_context_ids": list(
                    answer.context_metadata.get("missing_required_context_ids") or []
                ),
                "required_context_coverage": answer.context_metadata.get("required_context_coverage"),
                "gold_context_coverage": _coverage(answer.context_chunk_ids, pair.gold_chunk_ids),
                "context_score_breakdowns": context_score_breakdowns,
            },
        ))
        generated.append(answer)
    return samples, generated


def _answer_generation_pairs(pairs: list[EvidenceQAPair], config: BenchmarkSuiteConfig) -> list[EvidenceQAPair]:
    sample_size = _answer_generation_sample_size(config)
    if sample_size is None:
        return list(pairs)
    return _stable_sample(list(pairs), sample_size=max(0, sample_size), seed=f"{config.split_seed}:answer_eval")


def _answer_generation_sample_size(config: BenchmarkSuiteConfig) -> int | None:
    if config.answer_eval_enabled:
        return config.answer_eval_sample_size
    requested_sizes: list[int | None] = []
    if _answer_judge_enabled(config):
        requested_sizes.append(config.answer_judge_sample_size)
    if config.spot_check_sample_size > 0:
        requested_sizes.append(config.spot_check_sample_size)
    if not requested_sizes:
        return 0
    if any(size is None for size in requested_sizes):
        return None
    return max(max(0, int(size)) for size in requested_sizes if size is not None)


def _build_answer_llm_call(*, max_tokens: int) -> LLMCall:
    from business.research.application.llm_client import build_unity_llm_call

    return build_unity_llm_call(max_tokens=max_tokens, temperature=0)


def _context_chunks_for_answer(retrieval: Any, context_chunk_ids: list[str]) -> list[PaperChunk]:
    candidates = [
        *getattr(retrieval, "child_chunks", []),
        *getattr(retrieval, "ref_chunks", []),
        *getattr(retrieval, "parent_chunks", []),
    ]
    by_id = {chunk.chunk_id: chunk for chunk in candidates}
    return [chunk for chunk_id in context_chunk_ids if (chunk := by_id.get(chunk_id)) is not None]


def _cited_chunk_ids(answer: str, context_chunk_ids: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"\[(\d+)\]", answer):
        index = int(match.group(1)) - 1
        if index < 0 or index >= len(context_chunk_ids):
            continue
        chunk_id = context_chunk_ids[index]
        if chunk_id not in seen:
            out.append(chunk_id)
            seen.add(chunk_id)
    return out


def _chunk_source_locator(chunk: PaperChunk | None) -> str:
    if chunk is None:
        return ""
    return str(chunk.metadata.get("source_locator") or chunk.metadata.get("source_ref") or "")


def _write_answer_samples(
    path: Path,
    samples: list[EvidenceAnswerSample],
    generated_answers: list[GeneratedAnswer],
    *,
    answer_result: Any | None = None,
) -> None:
    score_by_key = _answer_score_by_key(answer_result)
    records = [
        _answer_sample_record(
            sample,
            generated,
            score=score_by_key.get(_answer_sample_key(sample)),
        )
        for sample, generated in zip(samples, generated_answers, strict=True)
    ]
    _write_jsonl(path, records)


def _answer_sample_record(
    sample: EvidenceAnswerSample,
    generated: GeneratedAnswer,
    *,
    score: Any | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "question": sample.pair.question,
        "paper_id": sample.pair.paper_id,
        "qa_type": sample.pair.qa_type,
        "expected_behavior": sample.pair.expected_behavior,
        "answer": sample.answer,
        "answer_facts": list(sample.pair.answer_facts),
        "gold_chunk_ids": list(sample.pair.gold_chunk_ids),
        "gold_source_locators": list(sample.pair.gold_source_locators),
        "context_chunk_ids": list(sample.context_chunk_ids),
        "cited_chunk_ids": list(sample.cited_chunk_ids),
        "cited_source_locators": list(sample.cited_source_locators),
        "contexts": list(generated.contexts),
        "context_score_breakdowns": dict(sample.metadata.get("context_score_breakdowns") or {}),
        "metadata": dict(sample.metadata),
        "context_metadata": dict(generated.context_metadata),
    }
    if score is not None:
        record["deterministic_scores"] = {
            "fact_coverage": score.fact_coverage,
            "fact_match_coverage": score.fact_coverage,
            "retrieval_context_coverage": score.retrieval_context_coverage,
            "citation_grounding": score.citation_grounding,
            "citation_gold_coverage": score.citation_gold_coverage,
            "source_locator_grounding": score.source_locator_grounding,
            "abstention_correct": score.abstention_correct,
            "answer_success": score.answer_success,
            "failure_reason": score.failure_reason,
            "matched_facts": list(score.matched_facts),
            "missing_facts": list(score.missing_facts),
        }
    return record


def _write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _context_score_breakdowns(chunks: list[PaperChunk]) -> dict[str, dict[str, float]]:
    return {
        chunk.chunk_id: breakdown
        for chunk in chunks
        if (breakdown := paper_chunk_to_rag_evidence(chunk).score_breakdown.to_dict())
    }


def _answer_judge_sample(
    generated_answers: list[GeneratedAnswer],
    config: BenchmarkSuiteConfig,
) -> list[GeneratedAnswer]:
    sample_size = config.answer_judge_sample_size
    if sample_size is None:
        return list(generated_answers)
    return list(generated_answers[:max(0, sample_size)])


async def _run_answer_judge(
    config: BenchmarkSuiteConfig,
    generated_answers: list[GeneratedAnswer],
) -> GenerationEvalResult:
    mode = str(config.answer_judge_mode or "none").strip().casefold()
    if mode != "llm":
        raise ValueError("answer_judge_mode must be 'none' or 'llm'")
    llm_call = config.answer_judge_llm_call or _build_answer_llm_call(max_tokens=300)
    return await GenerationEvaluator(llm_call).evaluate(generated_answers)


def _write_spot_check_report(
    config: BenchmarkSuiteConfig,
    *,
    output_dir: Path,
    answer_samples: list[EvidenceAnswerSample],
    generated_answers: list[GeneratedAnswer],
    answer_result: Any | None,
) -> SpotCheckReport | None:
    if config.spot_check_sample_size <= 0:
        return _spot_check_report_from_annotations(config, output_dir=output_dir, sample_size=0)
    score_by_key = _answer_score_by_key(answer_result)
    records = [
        _answer_sample_record(
            sample,
            generated,
            score=score_by_key.get(_answer_sample_key(sample)),
        )
        for sample, generated in zip(answer_samples, generated_answers, strict=True)
    ]
    records = _spot_check_sample_records(records, config)
    path = output_dir / "spot_check_samples.jsonl"
    _write_jsonl(path, records)
    annotation_summary = _spot_check_report_from_annotations(
        config,
        output_dir=output_dir,
        sample_size=len(records),
        sample_path=path,
    )
    return annotation_summary or SpotCheckReport(
        sample_path=str(path),
        sample_size=len(records),
    )


def _answer_score_by_key(answer_result: Any | None) -> dict[tuple[str, str, str], Any]:
    if answer_result is None:
        return {}
    return {
        _answer_sample_key(score.sample): score
        for score in answer_result.scores
    }


def _answer_sample_key(sample: EvidenceAnswerSample) -> tuple[str, str, str]:
    return (sample.pair.paper_id, sample.pair.qa_type, sample.pair.question)


def _spot_check_sample_records(records: list[dict[str, Any]], config: BenchmarkSuiteConfig) -> list[dict[str, Any]]:
    def priority(record: dict[str, Any]) -> tuple[int, str]:
        scores = record.get("deterministic_scores") or {}
        failed = scores.get("answer_success") is False
        key = _stable_split_key(config.split_seed, f"spot:{record.get('paper_id')}:{record.get('question')}")
        return (0 if failed else 1, key)

    ordered = sorted(records, key=priority)
    return ordered[:max(0, config.spot_check_sample_size)]


def _spot_check_report_from_annotations(
    config: BenchmarkSuiteConfig,
    *,
    output_dir: Path,
    sample_size: int,
    sample_path: Path | None = None,
) -> SpotCheckReport | None:
    path = config.spot_check_annotations_path
    if path is None:
        return None
    if not path.exists():
        raise FileNotFoundError(f"spot check annotations not found: {path}")
    counts: Counter[str] = Counter()
    annotated = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            item = json.loads(line)
            label = str(
                item.get("label")
                or item.get("status")
                or item.get("verdict")
                or "unknown"
            ).strip().casefold() or "unknown"
            counts[label] += 1
            annotated += 1
    return SpotCheckReport(
        sample_path=str(sample_path or output_dir / "spot_check_samples.jsonl"),
        sample_size=sample_size,
        annotation_path=str(path),
        annotated_count=annotated,
        label_counts=dict(counts),
    )


def _evaluate_fixed_window_baseline(
    config: BenchmarkSuiteConfig,
    chunks: list[PaperChunk],
    pairs: list[EvidenceQAPair],
    output_dir: Path,
) -> dict[str, Any]:
    baseline_chunks = FixedWindowBaselineChunker(FixedWindowChunkerConfig(
        window_tokens=config.fixed_window_tokens,
        overlap_tokens=config.fixed_window_overlap_tokens,
    )).chunk(chunks)
    retriever, _visual_store = _build_live_retriever(
        baseline_chunks,
        visual_enabled=False,
        image_root=None,
        retrieval_policy="",
    )
    retrieval = EvidenceRetrievalEvaluator(retriever).evaluate(pairs)
    metadata = {
        "mode": "fixed_window_baseline",
        "chunks_total": len(baseline_chunks),
        "window_tokens": config.fixed_window_tokens,
        "overlap_tokens": FixedWindowChunkerConfig(
            window_tokens=config.fixed_window_tokens,
            overlap_tokens=config.fixed_window_overlap_tokens,
        ).overlap_tokens,
    }
    report = EvidenceRegressionReport(retrieval=retrieval, metadata=metadata)
    report.write(output_dir)
    return json.loads((output_dir / "evidence_regression_report.json").read_text(encoding="utf-8"))


def _compare_reports(candidate_report: dict[str, Any], baseline_report: dict[str, Any]) -> dict[str, Any]:
    candidate = candidate_report.get("retrieval") or {}
    baseline = baseline_report.get("retrieval") or {}
    deltas: dict[str, Any] = {
        "mrr": _metric(candidate, "mrr") - _metric(baseline, "mrr"),
        "by_k": {},
    }
    for k in ("1", "3", "5", "10"):
        c = ((candidate.get("by_k") or {}).get(k) or {})
        b = ((baseline.get("by_k") or {}).get(k) or {})
        deltas["by_k"][k] = {
            "hit_rate": _metric(c, "hit_rate") - _metric(b, "hit_rate"),
            "evidence_coverage": _metric(c, "evidence_coverage") - _metric(b, "evidence_coverage"),
            "source_locator_coverage": _metric(c, "source_locator_coverage") - _metric(b, "source_locator_coverage"),
        }
    relative = {
        "mrr": _relative_improvement(_metric(candidate, "mrr"), _metric(baseline, "mrr")),
        "by_k": {},
    }
    for k in ("1", "3", "5", "10"):
        c = ((candidate.get("by_k") or {}).get(k) or {})
        b = ((baseline.get("by_k") or {}).get(k) or {})
        relative["by_k"][k] = {
            "hit_rate": _relative_improvement(_metric(c, "hit_rate"), _metric(b, "hit_rate")),
            "evidence_coverage": _relative_improvement(_metric(c, "evidence_coverage"), _metric(b, "evidence_coverage")),
            "source_locator_coverage": _relative_improvement(_metric(c, "source_locator_coverage"), _metric(b, "source_locator_coverage")),
        }
    return {
        "baseline_name": "fixed_window",
        "candidate_name": "paper_visual_rag_tuned",
        "baseline": _summary_from_report(baseline_report),
        "candidate": _summary_from_report(candidate_report),
        "macro_by_qa_type": _macro_by_qa_type(candidate, baseline),
        "deltas": deltas,
        "relative_improvement": relative,
    }


def _run_gold_judge(
    config: BenchmarkSuiteConfig,
    audit: GoldEvidenceAuditReport,
) -> GoldEvidenceJudgeReport | None:
    mode = str(config.gold_judge_mode or "none").strip().casefold()
    if mode in {"", "none", "off", "false", "0"}:
        return None
    sample_size = config.gold_judge_sample_size
    items = list(audit.items)
    if sample_size is not None:
        items = items[:max(0, sample_size)]
    judge = config.gold_evidence_judge
    if judge is None:
        if mode != "llm":
            raise ValueError("gold_evidence_judge is required when gold_judge_mode is not 'none' or 'llm'")
        judge = OpenAICompatibleGoldEvidenceJudge.from_env(
            max_evidence_chars=config.gold_judge_max_evidence_chars,
        )
    return judge.judge(items)


def _audit_pair(pair: EvidenceQAPair, chunks_by_id: dict[str, PaperChunk]) -> GoldEvidenceAuditItem:
    missing = tuple(chunk_id for chunk_id in pair.gold_chunk_ids if chunk_id not in chunks_by_id)
    gold_chunks = [chunks_by_id[chunk_id] for chunk_id in pair.gold_chunk_ids if chunk_id in chunks_by_id]
    answer_facts_present = any(str(fact).strip() for fact in pair.answer_facts)
    locator_count = sum(1 for chunk in gold_chunks if chunk.metadata.get("source_locator") or chunk.metadata.get("source_ref"))
    image_count = sum(1 for chunk in gold_chunks if chunk.metadata.get("image_ref"))
    required_types = set(pair.required_evidence_types)
    available_types = {_evidence_type(chunk) for chunk in gold_chunks}
    if missing:
        status = "fail"
        reason = "missing_gold_chunks"
    elif required_types and not required_types.issubset(available_types):
        status = "warning"
        reason = "required_evidence_type_not_fully_represented"
    elif pair.qa_type in {"figure_qa", "table_qa"} and image_count == 0:
        status = "warning"
        reason = "visual_qa_without_image_ref"
    elif not answer_facts_present and pair.expected_behavior == "answer":
        status = "warning"
        reason = "answerable_pair_without_answer_facts"
    else:
        status = "pass"
        reason = "ok"
    return GoldEvidenceAuditItem(
        question=pair.question,
        paper_id=pair.paper_id,
        qa_type=pair.qa_type,
        status=status,
        reason=reason,
        gold_chunk_ids=tuple(pair.gold_chunk_ids),
        missing_chunk_ids=missing,
        answer_facts_present=answer_facts_present,
        source_locator_count=locator_count,
        image_ref_count=image_count,
        answer_facts=tuple(str(fact) for fact in pair.answer_facts if str(fact).strip())[:3],
        evidence_previews=tuple(_evidence_preview(chunk) for chunk in gold_chunks[:5]),
    )


def _target_counts(pairs: Iterable[EvidenceQAPair]) -> dict[str, int]:
    counts = Counter(pair.qa_type for pair in pairs if pair.qa_type in DEFAULT_TARGET_QA_TYPES)
    return dict(sorted(counts.items()))


def _suite_warnings(
    *,
    paper_count: int,
    target_counts: dict[str, int],
    config: BenchmarkSuiteConfig,
    splits: dict[str, BenchmarkSplit],
    audit: GoldEvidenceAuditReport,
    judge_report: GoldEvidenceJudgeReport | None,
    candidate_report: dict[str, Any],
) -> list[str]:
    warnings: list[str] = []
    if paper_count < config.min_papers:
        warnings.append(f"paper_count_below_target:{paper_count}<{config.min_papers}")
    for qa_type in DEFAULT_TARGET_QA_TYPES:
        count = target_counts.get(qa_type, 0)
        if count < config.target_min_per_type:
            warnings.append(f"qa_type_count_below_target:{qa_type}:{count}<{config.target_min_per_type}")
    for name in ("train", "dev", "test"):
        if not splits.get(name) or splits[name].pair_count == 0:
            warnings.append(f"empty_split:{name}")
    warnings.extend(_split_distribution_warnings(splits))
    if audit.failed:
        warnings.append(f"gold_audit_failed:{audit.failed}")
    if audit.warning:
        warnings.append(f"gold_audit_warning:{audit.warning}")
    if judge_report is not None:
        if judge_report.failed:
            warnings.append(f"gold_judge_failed:{judge_report.failed}")
        if judge_report.warning:
            warnings.append(f"gold_judge_warning:{judge_report.warning}")
        if judge_report.error:
            warnings.append(f"gold_judge_error:{judge_report.error}")
    elif _is_blind_question_profile(config.question_profile):
        warnings.append(f"{_normalize_question_profile(config.question_profile)}_without_gold_judge")
    if candidate_report.get("passed") is False:
        warnings.append("candidate_quality_gate_failed")
        for issue in candidate_report.get("issues") or []:
            warnings.append(f"candidate_quality_issue:{issue}")
    return warnings


def _split_distribution_warnings(splits: dict[str, BenchmarkSplit]) -> list[str]:
    test = splits.get("test")
    if test is None or test.pair_count <= 0:
        return []
    warnings: list[str] = []
    answerable_count = sum(
        count for qa_type, count in test.qa_type_counts.items()
        if qa_type != "negative_qa"
    )
    if answerable_count <= 0:
        return warnings
    for qa_type, count in sorted(test.qa_type_counts.items()):
        if qa_type == "negative_qa":
            continue
        share = count / answerable_count
        if share >= 0.45:
            warnings.append(f"test_split_qa_type_dominates:{qa_type}:{share:.2f}")
    return warnings


def _write_suite_report(result: BenchmarkSuiteResult) -> None:
    payload = result.to_dict()
    (result.output_dir / "benchmark_suite_report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (result.output_dir / "benchmark_suite_report.md").write_text(_suite_markdown(payload), encoding="utf-8")


def _suite_markdown(payload: dict[str, Any]) -> str:
    candidate = payload["candidate_test_report"]["retrieval"]
    baseline_report = payload.get("baseline_test_report")
    baseline = (baseline_report or {}).get("retrieval") or None
    ab_report = payload.get("ab_report") or None
    relative_mrr = ((ab_report or {}).get("relative_improvement") or {}).get("mrr")
    macro = (ab_report or {}).get("macro_by_qa_type") or {}
    lines = [
        "# Paper RAG Benchmark Suite",
        "",
        f"- papers: `{payload['papers_total']}`",
        f"- chunks: `{payload['chunks_total']}`",
        f"- pairs: `{payload['pairs_total']}`",
        f"- warnings: `{len(payload['warnings'])}`",
        f"- reported split: `{payload['evaluation_protocol']['reported_split']}`",
        f"- question profile: `{payload['evaluation_protocol'].get('question_profile', 'template')}`",
        f"- blind test: `{payload['evaluation_protocol'].get('blind_test', False)}`",
        "",
        "## Test Metrics",
        "",
        f"- candidate Hit@10: `{candidate['by_k']['10']['hit_rate']:.3f}`",
        f"- candidate MRR: `{candidate['mrr']:.3f}`",
    ]
    if baseline is not None and ab_report is not None:
        lines.extend([
            f"- fixed-window Hit@10: `{baseline['by_k']['10']['hit_rate']:.3f}`",
            f"- fixed-window MRR: `{baseline['mrr']:.3f}`",
            f"- MRR delta: `{ab_report['deltas']['mrr']:.3f}`",
            f"- MRR relative improvement: `{_format_optional_ratio(relative_mrr)}`",
        ])
    if macro:
        lines.extend([
            f"- candidate macro Hit@10: `{macro['candidate']['macro_hit_at_10']:.3f}`",
            f"- candidate macro MRR: `{macro['candidate']['macro_mrr']:.3f}`",
            f"- fixed-window macro Hit@10: `{macro['baseline']['macro_hit_at_10']:.3f}`",
            f"- fixed-window macro MRR: `{macro['baseline']['macro_mrr']:.3f}`",
        ])
    score_breakdown = candidate.get("score_breakdown_summary") or {}
    score_components = score_breakdown.get("components") or {}
    if score_components:
        lines.extend([
            "",
            "## Score Breakdown",
            "",
            f"- top_k: `{score_breakdown.get('top_k')}`",
            f"- evidence_count: `{score_breakdown.get('evidence_count', 0)}`",
            "",
            "| Component | count | avg | min | max |",
            "| --- | ---: | ---: | ---: | ---: |",
        ])
        for component, stats in score_components.items():
            lines.append(
                f"| `{component}` | `{stats.get('count', 0)}` | "
                f"`{stats.get('avg', 0.0):.3f}` | `{stats.get('min', 0.0):.3f}` | "
                f"`{stats.get('max', 0.0):.3f}` |"
            )
    field_embedding_distribution = candidate.get("field_embedding_distribution") or {}
    field_by_name = field_embedding_distribution.get("by_field") or {}
    field_search_hits = field_embedding_distribution.get("search_hits_by_field") or {}
    if field_by_name or field_search_hits:
        lines.extend([
            "",
            "## Field Embedding Distribution",
            "",
            f"- top_k: `{field_embedding_distribution.get('top_k')}`",
            f"- matched_evidence_count: `{field_embedding_distribution.get('matched_evidence_count', 0)}`",
        ])
        if field_by_name:
            lines.extend([
                "",
                "| Field | count | avg | max |",
                "| --- | ---: | ---: | ---: |",
            ])
            for field_name, stats in sorted(field_by_name.items()):
                lines.append(
                    f"| `{field_name}` | `{stats.get('count', 0)}` | "
                    f"`{stats.get('avg_score', 0.0):.3f}` | `{stats.get('max_score', 0.0):.3f}` |"
                )
        if field_search_hits:
            lines.extend(["", "| Search hit field | count |", "| --- | ---: |"])
            for field_name, count in sorted(field_search_hits.items()):
                lines.append(f"| `{field_name}` | `{count}` |")
    route_distribution = candidate.get("route_distribution") or {}
    intent_distribution = candidate.get("intent_distribution") or {}
    intent_confusion = candidate.get("intent_confusion") or {}
    if route_distribution or intent_distribution:
        lines.extend(["", "## Route Distribution", ""])
        if intent_distribution:
            lines.extend([
                "| Intent | count |",
                "| --- | ---: |",
            ])
            for intent, count in sorted(intent_distribution.items()):
                lines.append(f"| `{intent}` | `{count}` |")
        if route_distribution:
            lines.extend([
                "",
                "| Recall route | count |",
                "| --- | ---: |",
            ])
            for route_name, count in sorted(route_distribution.items()):
                lines.append(f"| `{route_name}` | `{count}` |")
    if intent_confusion:
        lines.extend([
            "",
            "## Intent Confusion",
            "",
            "| QA type | routed intents |",
            "| --- | --- |",
        ])
        for qa_type, counts in sorted(intent_confusion.items()):
            rendered = ", ".join(
                f"`{intent}`={count}"
                for intent, count in sorted(counts.items())
            )
            lines.append(f"| `{qa_type}` | {rendered} |")
    lines.extend(["", "## Test Metrics By QA Type", ""])
    if baseline is not None:
        lines.extend([
            "| QA type | n | candidate Hit@10 | candidate MRR | fixed-window Hit@10 | fixed-window MRR |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
            *_qa_type_metric_rows(candidate, baseline),
        ])
    else:
        lines.extend([
            "| QA type | n | candidate Hit@10 | candidate MRR |",
            "| --- | ---: | ---: | ---: |",
            *_qa_type_metric_rows(candidate, None),
        ])
    lines.extend([
        "",
        "## QA Type Counts",
    ])
    for qa_type, count in payload["target_qa_counts"].items():
        lines.append(f"- {qa_type}: `{count}`")
    question_audit = payload.get("question_audit") or {}
    if question_audit:
        lines.extend([
            "",
            "## Question Ambiguity Audit",
            "",
            f"- duplicate question rate: `{_metric(question_audit, 'duplicate_question_rate'):.3f}`",
            f"- ambiguous question rate: `{_metric(question_audit, 'ambiguous_question_rate'):.3f}`",
            f"- missing semantic anchor rate: `{_metric(question_audit, 'missing_semantic_anchor_rate'):.3f}`",
            f"- label leakage rate: `{_metric(question_audit, 'label_leakage_rate'):.3f}`",
            f"- caption copy rate: `{_metric(question_audit, 'caption_copy_rate'):.3f}`",
        ])
        by_qa_type = question_audit.get("by_qa_type") or {}
        if by_qa_type:
            lines.extend([
                "",
                "| QA type | n | duplicate | ambiguous | missing anchor | label leakage | caption copy |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ])
            for qa_type, counts in sorted(by_qa_type.items()):
                lines.append(
                    f"| {qa_type} | {counts.get('total', 0)} | "
                    f"{counts.get('duplicate_question', 0)} | {counts.get('ambiguous_question', 0)} | "
                    f"{counts.get('missing_semantic_anchor', 0)} | {counts.get('label_leakage', 0)} | "
                    f"{counts.get('caption_copy', 0)} |"
                )
    answer = payload["candidate_test_report"].get("answer")
    if answer:
        lines.extend([
            "",
            "## Answer Metrics",
            "",
            f"- answer success rate: `{answer['success_rate']:.3f}`",
            f"- answer fact coverage: `{answer['answer_fact_coverage']:.3f}`",
            f"- retrieval context coverage: `{answer['retrieval_context_coverage']:.3f}`",
            f"- citation grounding: `{answer['citation_grounding_score']:.3f}`",
            f"- citation gold coverage: `{answer['citation_gold_coverage']:.3f}`",
            f"- source locator grounding: `{answer['source_locator_grounding_score']:.3f}`",
            f"- abstention accuracy: `{answer['abstention_accuracy']:.3f}`",
        ])
        failure_counts = answer.get("failure_reason_counts") or {}
        if failure_counts:
            lines.append("- failure reasons:")
            for reason, count in sorted(failure_counts.items()):
                lines.append(f"  - `{reason}`: `{count}`")
    generation = payload["candidate_test_report"].get("generation")
    if generation:
        lines.extend([
            "",
            "## Generation Judge",
            "",
            f"- faithfulness: `{generation['faithfulness']:.3f}`",
            f"- answer relevancy: `{generation['answer_relevancy']:.3f}`",
            f"- context precision: `{generation['context_precision']:.3f}`",
            f"- judged samples: `{generation['total']}`",
        ])
    spot_check = payload.get("spot_check")
    if spot_check:
        lines.extend([
            "",
            "## Spot Check",
            "",
            f"- sample_path: `{spot_check['sample_path']}`",
            f"- sample_size: `{spot_check['sample_size']}`",
            f"- annotated_count: `{spot_check['annotated_count']}`",
        ])
        if spot_check.get("label_counts"):
            for label, count in sorted(spot_check["label_counts"].items()):
                lines.append(f"- {label}: `{count}`")
    lines.extend([
        "",
        "## Splits",
    ])
    for name, split in payload["splits"].items():
        lines.append(f"- {name}: `{len(split['paper_ids'])}` papers, `{split['pair_count']}` pairs")
    audit_by_type = (payload.get("gold_audit") or {}).get("by_qa_type") or {}
    if audit_by_type:
        lines.extend([
            "",
            "## Gold Audit By QA Type",
            "",
            "| QA type | pass | warning | fail |",
            "| --- | ---: | ---: | ---: |",
        ])
        for qa_type, counts in sorted(audit_by_type.items()):
            lines.append(
                f"| {qa_type} | {counts.get('pass', 0)} | "
                f"{counts.get('warning', 0)} | {counts.get('fail', 0)} |"
            )
    if payload.get("gold_judge"):
        judge = payload["gold_judge"]
        lines.extend([
            "",
            "## Gold Judge",
            "",
            f"- mode: `{judge['mode']}`",
            f"- model: `{judge['model']}`",
            f"- sample_size: `{judge['sample_size']}`",
            f"- pass/warning/fail/error: `{judge['passed']}/{judge['warning']}/{judge['failed']}/{judge['error']}`",
        ])
    if payload["warnings"]:
        lines.extend(["", "## Warnings", *[f"- `{warning}`" for warning in payload["warnings"]]])
    return "\n".join(lines) + "\n"


def _qa_type_metric_rows(candidate: dict[str, Any], baseline: dict[str, Any] | None) -> list[str]:
    rows: list[str] = []
    candidate_by_type = candidate.get("by_qa_type") or {}
    baseline_by_type = (baseline or {}).get("by_qa_type") or {}
    for qa_type in sorted(set(candidate_by_type) | set(baseline_by_type)):
        current = candidate_by_type.get(qa_type) or {}
        base = baseline_by_type.get(qa_type) or {}
        answerable_total = int(current.get("answerable_total") or base.get("answerable_total") or 0)
        if answerable_total <= 0:
            continue
        values = [
            qa_type,
            str(answerable_total),
            f"{_hit_at_10(current):.3f}",
            f"{_metric(current, 'mrr'):.3f}",
        ]
        if baseline is not None:
            values.extend([
                f"{_hit_at_10(base):.3f}",
                f"{_metric(base, 'mrr'):.3f}",
            ])
        rows.append("| " + " | ".join(values) + " |")
    if baseline is not None:
        return rows or ["| none | 0 | 0.000 | 0.000 | 0.000 | 0.000 |"]
    return rows or ["| none | 0 | 0.000 | 0.000 |"]


def _macro_by_qa_type(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate": _macro_summary(candidate),
        "baseline": _macro_summary(baseline),
    }


def _macro_summary(retrieval: dict[str, Any]) -> dict[str, Any]:
    values = [
        item for item in (retrieval.get("by_qa_type") or {}).values()
        if int(item.get("answerable_total") or 0) > 0
    ]
    return {
        "qa_types": len(values),
        "macro_hit_at_10": _average([_hit_at_10(item) for item in values]),
        "macro_mrr": _average([_metric(item, "mrr") for item in values]),
    }


def _hit_at_10(retrieval: dict[str, Any]) -> float:
    return _metric(((retrieval.get("by_k") or {}).get("10") or {}), "hit_rate")


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _coverage(retrieved: list[str], required: list[str]) -> float | None:
    required_set = set(_unique_texts(required))
    if not required_set:
        return None
    return len(required_set.intersection(_unique_texts(retrieved))) / len(required_set)


def _unique_texts(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        out.append(text)
        seen.add(text)
    return out


def _summary_from_report(report: dict[str, Any]) -> dict[str, Any]:
    retrieval = report.get("retrieval") or {}
    by_k = retrieval.get("by_k") or {}
    return {
        "answerable_total": retrieval.get("answerable_total", 0),
        "hit_at_10": (by_k.get("10") or {}).get("hit_rate", 0.0),
        "mrr": retrieval.get("mrr", 0.0),
    }


def _metric(values: dict[str, Any], key: str) -> float:
    try:
        return float(values.get(key, 0.0))
    except (TypeError, ValueError):
        return 0.0


def _relative_improvement(candidate: float, baseline: float) -> float | None:
    if baseline <= 0.0:
        return None
    return (candidate - baseline) / baseline


def _format_optional_ratio(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _split_to_dict(split: BenchmarkSplit) -> dict[str, Any]:
    return {
        "name": split.name,
        "paper_ids": list(split.paper_ids),
        "pair_count": split.pair_count,
        "qa_type_counts": dict(split.qa_type_counts),
    }


def _stable_split_key(seed: str, paper_id: str) -> str:
    return hashlib.sha256(f"{seed}:{paper_id}".encode("utf-8")).hexdigest()


def _stable_sample(values: list[EvidenceQAPair], *, sample_size: int, seed: str) -> list[EvidenceQAPair]:
    ordered = sorted(values, key=lambda pair: _stable_split_key(seed, f"{pair.paper_id}:{pair.question}"))
    return ordered[:sample_size] if sample_size else []


def _evidence_type(chunk: PaperChunk) -> str:
    if chunk.chunk_type == "formula" or chunk.has_formula:
        return "formula"
    if chunk.chunk_type == "figure" or chunk.has_figure:
        return "figure"
    if chunk.chunk_type == "table" or chunk.has_table:
        return "table"
    return chunk.chunk_type


def _evidence_preview(chunk: PaperChunk) -> dict[str, Any]:
    return {
        "chunk_id": chunk.chunk_id,
        "chunk_type": chunk.chunk_type,
        "section_title": chunk.section_title,
        "source_locator": chunk.metadata.get("source_locator") or chunk.metadata.get("source_ref") or "",
        "image_ref": chunk.metadata.get("image_ref") or "",
        "content_preview": " ".join(chunk.content.split())[:360],
    }


def _judge_prompt(item: GoldEvidenceAuditItem, max_evidence_chars: int) -> str:
    evidence_lines = []
    for preview in item.evidence_previews:
        evidence_lines.append(json.dumps({
            "chunk_id": preview.get("chunk_id"),
            "chunk_type": preview.get("chunk_type"),
            "section_title": preview.get("section_title"),
            "source_locator": preview.get("source_locator"),
            "content_preview": str(preview.get("content_preview") or "")[:max_evidence_chars],
        }, ensure_ascii=False))
    return "\n".join([
        "You are auditing a paper QA benchmark gold evidence item.",
        "Return JSON only with keys: supported(boolean), confidence(number 0-1), reason(string).",
        "Judge whether the evidence previews are enough to support the question and expected answer facts.",
        "",
        f"Question: {item.question}",
        f"QA type: {item.qa_type}",
        f"Answer facts: {json.dumps(list(item.answer_facts), ensure_ascii=False)}",
        "Evidence previews:",
        *evidence_lines,
    ])


def _extract_json_object(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        payload = json.loads(text[start:end + 1])
    if not isinstance(payload, dict):
        raise ValueError("judge response must be a JSON object")
    return payload


def _clamped_float(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, parsed))


__all__ = [
    "BenchmarkSplit",
    "BenchmarkSuiteConfig",
    "BenchmarkSuiteResult",
    "GoldEvidenceAuditItem",
    "GoldEvidenceAuditReport",
    "GoldEvidenceJudgeItem",
    "GoldEvidenceJudgeReport",
    "OpenAICompatibleGoldEvidenceJudge",
    "audit_gold_evidence",
    "run_benchmark_suite",
    "split_paper_ids",
]
