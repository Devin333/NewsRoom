from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from business.research.rag.evaluation.ci_eval_gate import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_RETRIEVAL_POLICY,
    parse_thresholds,
    run_ci_eval_gate,
)


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = run_ci_eval_gate(
        output_dir=Path(args.output_dir),
        retrieval_policy=args.retrieval_policy,
        retrieval_thresholds=parse_thresholds(args.threshold),
        promotion_thresholds=parse_thresholds(args.promotion_threshold),
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), end="\n")
    return 0 if result.passed else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m business.research.rag.cli.run_ci_eval_gate",
        description="Run the deterministic Paper RAG CI retrieval and promotion gate.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for generated fixtures and CI eval artifacts.",
    )
    parser.add_argument(
        "--retrieval-policy",
        default=DEFAULT_RETRIEVAL_POLICY,
        help="Retrieval policy used by the in-memory live retrieval evaluator.",
    )
    parser.add_argument(
        "--threshold",
        action="append",
        default=[],
        metavar="METRIC=VALUE",
        help="Override or add evidence report threshold, for example retrieval.hit_rate=0.8.",
    )
    parser.add_argument(
        "--promotion-threshold",
        action="append",
        default=[],
        metavar="CHECK=VALUE",
        help="Override or add CI promotion threshold, for example overall_hit_at_3=0.8.",
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
