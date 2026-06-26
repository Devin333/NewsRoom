from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from business.research.rag.benchmark_suite import BenchmarkSuiteConfig, run_benchmark_suite


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = run_benchmark_suite(BenchmarkSuiteConfig(
        papers_dir=Path(args.papers_dir),
        output_dir=Path(args.output_dir),
        image_root=Path(args.image_root) if args.image_root else Path(args.papers_dir),
        retrieval_policy=args.retrieval_policy,
        max_pairs_per_type=args.max_pairs_per_type,
        min_papers=args.min_papers,
        target_min_per_type=args.target_min_per_type,
        split_seed=args.split_seed,
        include_negative=not args.no_negative,
        visual=not args.no_visual,
        page_visual=not args.no_page_visual,
        render_page_visual=not args.no_render_page_visual,
        gold_audit_sample_size=args.gold_audit_sample_size,
        gold_judge_mode=args.gold_judge,
        gold_judge_sample_size=args.gold_judge_sample_size,
        gold_judge_max_evidence_chars=args.gold_judge_max_evidence_chars,
        fixed_window_tokens=args.fixed_window_tokens,
        fixed_window_overlap_tokens=args.fixed_window_overlap_tokens,
    ))
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), end="\n")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m business.research.rag.run_benchmark_suite",
        description="Run train/dev/test paper RAG benchmark with fixed-window baseline and gold evidence audit.",
    )
    parser.add_argument("--papers-dir", required=True, help="Directory containing per-paper research_document.json files.")
    parser.add_argument("--output-dir", required=True, help="Directory for benchmark suite artifacts.")
    parser.add_argument("--image-root", help="Root used to resolve relative figure/table image refs.")
    parser.add_argument("--retrieval-policy", default="paper_visual_rag_tuned")
    parser.add_argument("--max-pairs-per-type", type=int, default=100)
    parser.add_argument("--min-papers", type=int, default=20)
    parser.add_argument("--target-min-per-type", type=int, default=50)
    parser.add_argument("--split-seed", default="paper-rag-benchmark-v1")
    parser.add_argument("--gold-audit-sample-size", type=int, default=30)
    parser.add_argument(
        "--gold-judge",
        choices=("none", "llm"),
        default="none",
        help="Optional gold evidence audit mode. 'llm' uses OPENAI_*-compatible chat settings.",
    )
    parser.add_argument(
        "--gold-judge-sample-size",
        type=int,
        help="Maximum sampled audit items to send to --gold-judge.",
    )
    parser.add_argument("--gold-judge-max-evidence-chars", type=int, default=1600)
    parser.add_argument("--fixed-window-tokens", type=int, default=220)
    parser.add_argument("--fixed-window-overlap-tokens", type=int)
    parser.add_argument("--no-negative", action="store_true")
    parser.add_argument("--no-visual", action="store_true")
    parser.add_argument("--no-page-visual", action="store_true")
    parser.add_argument("--no-render-page-visual", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
