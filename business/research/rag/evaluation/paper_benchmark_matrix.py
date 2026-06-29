from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from business.research.rag.evaluation.paper_benchmark_suite import (
    BenchmarkSuiteConfig,
    BenchmarkSuiteResult,
    run_benchmark_suite,
)


@dataclass(frozen=True)
class BenchmarkMatrixDataset:
    name: str
    papers_dir: Path
    image_root: Path | None = None

    def __post_init__(self) -> None:
        name = str(self.name or "").strip()
        if not name:
            raise ValueError("dataset name is required")
        object.__setattr__(self, "name", _safe_dataset_name(name))
        object.__setattr__(self, "papers_dir", Path(self.papers_dir))
        if self.image_root is not None:
            object.__setattr__(self, "image_root", Path(self.image_root))


@dataclass
class BenchmarkMatrixConfig:
    datasets: tuple[BenchmarkMatrixDataset, ...]
    output_dir: Path
    retrieval_policy: str = "paper_blind_semantic_rag_v1"
    question_profile: str = "blind_semantic"
    max_pairs_per_type: int = 100
    min_papers: int = 20
    target_min_per_type: int = 50
    split_seed: str = "paper-rag-benchmark-v1"
    visual: bool = True
    page_visual: bool = True
    render_page_visual: bool = True
    lightweight_reranker: bool = False
    gold_audit_sample_size: int = 30
    answer_eval_enabled: bool = False
    answer_eval_sample_size: int | None = None
    spot_check_sample_size: int = 0
    quality_thresholds: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class BenchmarkMatrixResult:
    output_dir: Path
    dataset_results: dict[str, BenchmarkSuiteResult]

    @property
    def ready_for_promotion(self) -> bool:
        return all(
            result.policy_promotion_checklist.ready_for_promotion
            for result in self.dataset_results.values()
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_dir": str(self.output_dir),
            "ready_for_promotion": self.ready_for_promotion,
            "datasets": {
                name: _dataset_summary(result)
                for name, result in sorted(self.dataset_results.items())
            },
        }

    def to_markdown(self) -> str:
        payload = self.to_dict()
        lines = [
            "# Paper RAG Benchmark Matrix",
            "",
            f"- ready_for_promotion: `{payload['ready_for_promotion']}`",
            f"- datasets: `{len(payload['datasets'])}`",
            "",
            "| Dataset | Papers | Pairs | Hit@10 | Eq Hit@10 | MRR | Answer success | Ready | Warnings |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |",
        ]
        for name, item in payload["datasets"].items():
            lines.append(
                f"| `{name}` | `{item['papers_total']}` | `{item['pairs_total']}` | "
                f"`{item['strict_hit_at_10']:.3f}` | `{item['equivalent_hit_at_10']:.3f}` | "
                f"`{item['mrr']:.3f}` | `{_format_optional_metric(item['answer_success_rate'])}` | "
                f"`{item['ready_for_promotion']}` | `{item['warning_count']}` |"
            )
        return "\n".join(lines).rstrip() + "\n"


def run_benchmark_matrix(config: BenchmarkMatrixConfig) -> BenchmarkMatrixResult:
    if not config.datasets:
        raise ValueError("at least one benchmark dataset is required")
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, BenchmarkSuiteResult] = {}
    for dataset in config.datasets:
        dataset_output = output_dir / dataset.name
        results[dataset.name] = run_benchmark_suite(
            BenchmarkSuiteConfig(
                papers_dir=dataset.papers_dir,
                output_dir=dataset_output,
                image_root=dataset.image_root or dataset.papers_dir,
                retrieval_policy=config.retrieval_policy,
                max_pairs_per_type=config.max_pairs_per_type,
                min_papers=config.min_papers,
                target_min_per_type=config.target_min_per_type,
                split_seed=config.split_seed,
                question_profile=config.question_profile,  # type: ignore[arg-type]
                visual=config.visual,
                page_visual=config.page_visual,
                render_page_visual=config.render_page_visual,
                lightweight_reranker=config.lightweight_reranker,
                gold_audit_sample_size=config.gold_audit_sample_size,
                answer_eval_enabled=config.answer_eval_enabled,
                answer_eval_sample_size=config.answer_eval_sample_size,
                spot_check_sample_size=config.spot_check_sample_size,
                quality_thresholds=dict(config.quality_thresholds),
            )
        )
    result = BenchmarkMatrixResult(output_dir=output_dir, dataset_results=results)
    (output_dir / "benchmark_matrix_report.json").write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "benchmark_matrix_report.md").write_text(result.to_markdown(), encoding="utf-8")
    return result


def _dataset_summary(result: BenchmarkSuiteResult) -> dict[str, Any]:
    report = result.candidate_test_report
    retrieval = report.get("retrieval") or {}
    by_10 = (retrieval.get("by_k") or {}).get("10") or {}
    answer = report.get("answer") or None
    return {
        "output_dir": str(result.output_dir),
        "papers_total": result.papers_total,
        "chunks_total": result.chunks_total,
        "pairs_total": result.pairs_total,
        "strict_hit_at_10": _float_metric(by_10, "strict_hit_rate"),
        "equivalent_hit_at_10": _float_metric(by_10, "equivalent_hit_rate"),
        "mrr": _float_metric(retrieval, "mrr"),
        "equivalent_mrr": _float_metric(retrieval, "equivalent_mrr"),
        "answer_success_rate": _float_metric(answer, "success_rate") if isinstance(answer, dict) else None,
        "true_missing_gold_rate": _float_metric(answer, "true_missing_gold_rate") if isinstance(answer, dict) else None,
        "ready_for_promotion": result.policy_promotion_checklist.ready_for_promotion,
        "warning_count": len(result.warnings),
        "warnings": list(result.warnings),
    }


def _safe_dataset_name(name: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in name.strip())


def _float_metric(values: dict[str, Any] | None, key: str) -> float:
    try:
        return float((values or {}).get(key, 0.0))
    except (TypeError, ValueError):
        return 0.0


def _format_optional_metric(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


__all__ = [
    "BenchmarkMatrixConfig",
    "BenchmarkMatrixDataset",
    "BenchmarkMatrixResult",
    "run_benchmark_matrix",
]
