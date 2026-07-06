from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from business.research.rag.evaluation.ci_eval_gate import (
    DEFAULT_RETRIEVAL_POLICY,
    parse_thresholds,
)
from business.research.rag.evaluation.live_answer_eval import (
    DEFAULT_OUTPUT_DIR,
    run_live_answer_eval,
)


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = run_live_answer_eval(
        output_dir=Path(args.output_dir),
        retrieval_policy=args.retrieval_policy,
        thresholds=parse_thresholds(args.threshold),
        max_pairs_per_type=args.max_pairs_per_type,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), end="\n")
    return 0 if result.passed else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m business.research.rag.cli.run_live_answer_eval",
        description="Run live Paper RAG answer evaluation against fixture papers.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for generated fixtures and live answer eval artifacts.",
    )
    parser.add_argument(
        "--retrieval-policy",
        default=DEFAULT_RETRIEVAL_POLICY,
        help="Retrieval policy used by the fixture-backed live retrieval evaluator.",
    )
    parser.add_argument(
        "--max-pairs-per-type",
        type=int,
        default=2,
        help="Maximum golden pairs per QA type for the live answer eval fixture corpus.",
    )
    parser.add_argument(
        "--threshold",
        action="append",
        default=[],
        metavar="METRIC=VALUE",
        help="Override or add live evidence threshold, for example answer.success_rate=0.5.",
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
