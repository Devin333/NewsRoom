from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol, Sequence

from business.research.document.models import PaperChunk
from business.research.application.llm_client import _browser_ua_transport
from business.research.rag.evidence_eval import (
    EvidenceGoldenSetBuilder,
    EvidenceQAPair,
    EvidenceRetrievalEvaluator,
    save_evidence_golden_set,
)
from business.research.rag.evaluation_report import EvidenceRegressionReport
from business.research.rag.fixed_window_baseline import FixedWindowBaselineChunker, FixedWindowChunkerConfig
from business.research.rag.page_visual_chunks import build_page_visual_chunks
from business.research.rag.run_evidence_eval import _build_live_retriever, _load_chunks_from_papers_dir
from framework.llm.clients.openai_compatible import LLMRetryPolicy, OpenAICompatibleClient, OpenAICompatibleConfig
from framework.llm.models.request import LLMRequest
from framework.shared.env import load_root_env

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
    items: tuple[GoldEvidenceAuditItem, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_size": self.sample_size,
            "passed": self.passed,
            "warning": self.warning,
            "failed": self.failed,
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
    gold_audit: GoldEvidenceAuditReport
    gold_judge: GoldEvidenceJudgeReport | None
    candidate_test_report: dict[str, Any]
    baseline_test_report: dict[str, Any]
    ab_report: dict[str, Any]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
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
                "test_policy": "candidate and fixed-window baseline are evaluated only on the test split",
            },
            "gold_audit": self.gold_audit.to_dict(),
            "gold_judge": self.gold_judge.to_dict() if self.gold_judge is not None else None,
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
    visual: bool = True
    page_visual: bool = True
    render_page_visual: bool = False
    gold_audit_sample_size: int = 30
    gold_judge_mode: str = "none"
    gold_judge_sample_size: int | None = None
    gold_judge_max_evidence_chars: int = 1600
    gold_evidence_judge: GoldEvidenceJudge | None = None
    fixed_window_tokens: int = 220
    fixed_window_overlap_tokens: int | None = None


def run_benchmark_suite(config: BenchmarkSuiteConfig) -> BenchmarkSuiteResult:
    output_dir = config.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    base_chunks, chunks = _load_suite_chunk_sets(config)
    gold_chunks = _gold_builder_chunks(base_chunks)
    paper_ids = sorted({chunk.paper_id for chunk in gold_chunks})
    pairs = EvidenceGoldenSetBuilder(
        max_pairs_per_type=config.max_pairs_per_type,
        include_negative=config.include_negative,
    ).build(gold_chunks)
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
    candidate_report = _evaluate_candidate(config, chunks, test_pairs, output_dir / "test" / "candidate")
    baseline_report = _evaluate_fixed_window_baseline(config, chunks, test_pairs, output_dir / "test" / "fixed_window")
    ab_report = _compare_reports(candidate_report, baseline_report)

    warnings = _suite_warnings(
        paper_count=len(paper_ids),
        target_counts=target_counts,
        config=config,
        splits=splits,
        audit=audit,
        judge_report=judge_report,
    )
    result = BenchmarkSuiteResult(
        output_dir=output_dir,
        papers_total=len(paper_ids),
        chunks_total=len(chunks),
        pairs_total=len(pairs),
        split_seed=config.split_seed,
        splits=splits,
        target_qa_counts=target_counts,
        gold_audit=audit,
        gold_judge=judge_report,
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
    return GoldEvidenceAuditReport(
        sample_size=len(items),
        passed=counts.get("pass", 0),
        warning=counts.get("warning", 0),
        failed=counts.get("fail", 0),
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
) -> dict[str, Any]:
    retriever, visual_store = _build_live_retriever(
        chunks,
        visual_enabled=config.visual,
        image_root=config.image_root or config.papers_dir,
        retrieval_policy=config.retrieval_policy,
    )
    retrieval = EvidenceRetrievalEvaluator(retriever).evaluate(pairs)
    metadata = {
        "mode": "candidate",
        "retrieval_policy": retriever.policy.name,
        "chunks_total": len(chunks),
        "visual_fusion_enabled": visual_store is not None,
        "visual_indexed_chunks": len(getattr(visual_store, "_vectors", {})) if visual_store is not None else 0,
    }
    report = EvidenceRegressionReport(retrieval=retrieval, metadata=metadata)
    report.write(output_dir)
    return json.loads((output_dir / "evidence_regression_report.json").read_text(encoding="utf-8"))


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
    baseline = payload["baseline_test_report"]["retrieval"]
    relative_mrr = payload["ab_report"]["relative_improvement"]["mrr"]
    lines = [
        "# Paper RAG Benchmark Suite",
        "",
        f"- papers: `{payload['papers_total']}`",
        f"- chunks: `{payload['chunks_total']}`",
        f"- pairs: `{payload['pairs_total']}`",
        f"- warnings: `{len(payload['warnings'])}`",
        f"- reported split: `{payload['evaluation_protocol']['reported_split']}`",
        "",
        "## Test Metrics",
        "",
        f"- candidate Hit@10: `{candidate['by_k']['10']['hit_rate']:.3f}`",
        f"- candidate MRR: `{candidate['mrr']:.3f}`",
        f"- fixed-window Hit@10: `{baseline['by_k']['10']['hit_rate']:.3f}`",
        f"- fixed-window MRR: `{baseline['mrr']:.3f}`",
        f"- MRR delta: `{payload['ab_report']['deltas']['mrr']:.3f}`",
        f"- MRR relative improvement: `{_format_optional_ratio(relative_mrr)}`",
        "",
        "## QA Type Counts",
    ]
    for qa_type, count in payload["target_qa_counts"].items():
        lines.append(f"- {qa_type}: `{count}`")
    lines.extend([
        "",
        "## Splits",
    ])
    for name, split in payload["splits"].items():
        lines.append(f"- {name}: `{len(split['paper_ids'])}` papers, `{split['pair_count']}` pairs")
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
