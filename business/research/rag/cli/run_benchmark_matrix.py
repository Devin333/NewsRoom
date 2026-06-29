from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from business.research.rag.evaluation.paper_benchmark_matrix import (
    BenchmarkMatrixConfig,
    BenchmarkMatrixDataset,
    run_benchmark_matrix,
)


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = run_benchmark_matrix(BenchmarkMatrixConfig(
        datasets=tuple(_parse_dataset(value) for value in args.dataset),
        output_dir=Path(args.output_dir),
        retrieval_policy=args.retrieval_policy,
        question_profile=args.question_profile,
        max_pairs_per_type=args.max_pairs_per_type,
        min_papers=args.min_papers,
        target_min_per_type=args.target_min_per_type,
        split_seed=args.split_seed,
        visual=not args.no_visual,
        page_visual=not args.no_page_visual,
        render_page_visual=not args.no_render_page_visual,
        lightweight_reranker=args.lightweight_reranker,
        gold_audit_sample_size=args.gold_audit_sample_size,
        answer_eval_enabled=args.answer_eval,
        answer_eval_sample_size=args.answer_eval_sample_size,
        spot_check_sample_size=args.spot_check_sample_size,
        quality_thresholds=_parse_thresholds(args.quality_threshold),
    ))
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), end="\n")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m business.research.rag.cli.run_benchmark_matrix",
        description="Run the Paper RAG benchmark suite across multiple held-out paper datasets.",
    )
    parser.add_argument(
        "--dataset",
        action="append",
        required=True,
        metavar="NAME=PATH",
        help="Dataset name and papers directory. Repeat for historical_38, new50_20260629, etc.",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--retrieval-policy", default="paper_blind_semantic_rag_v1")
    parser.add_argument(
        "--question-profile",
        choices=("template", "blind_detemplated", "blind_semantic"),
        default="blind_semantic",
    )
    parser.add_argument("--max-pairs-per-type", type=int, default=100)
    parser.add_argument("--min-papers", type=int, default=20)
    parser.add_argument("--target-min-per-type", type=int, default=50)
    parser.add_argument("--split-seed", default="paper-rag-benchmark-v1")
    parser.add_argument("--gold-audit-sample-size", type=int, default=30)
    parser.add_argument("--answer-eval", action="store_true")
    parser.add_argument("--answer-eval-sample-size", type=int)
    parser.add_argument("--spot-check-sample-size", type=int, default=0)
    parser.add_argument("--quality-threshold", action="append", default=[], metavar="METRIC=VALUE")
    parser.add_argument("--no-visual", action="store_true")
    parser.add_argument("--no-page-visual", action="store_true")
    parser.add_argument("--no-render-page-visual", action="store_true")
    parser.add_argument("--lightweight-reranker", action="store_true")
    return parser


def _parse_dataset(value: str) -> BenchmarkMatrixDataset:
    if "=" not in value:
        raise ValueError(f"dataset must use NAME=PATH form: {value!r}")
    name, raw_path = value.split("=", 1)
    name = name.strip()
    raw_path = raw_path.strip()
    if not name or not raw_path:
        raise ValueError(f"dataset must include both name and path: {value!r}")
    return BenchmarkMatrixDataset(name=name, papers_dir=Path(raw_path))


def _parse_thresholds(values: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for raw in values:
        if "=" not in raw:
            raise ValueError(f"threshold must be METRIC=VALUE: {raw!r}")
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"threshold metric is empty: {raw!r}")
        out[key] = float(value)
    return out


if __name__ == "__main__":
    raise SystemExit(main())
