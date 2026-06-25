from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Sequence

from business.research.rag.evaluation_report import EvidenceRegressionReport
from business.research.rag.evidence_eval import load_evidence_golden_set


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    pairs = load_evidence_golden_set(args.golden_set)
    metadata = {
        "golden_set": str(Path(args.golden_set)),
        "total_pairs": len(pairs),
        "mode": "summary",
    }
    qa_type_counts = Counter(pair.qa_type for pair in pairs)
    behavior_counts = Counter(pair.expected_behavior for pair in pairs)
    metadata["qa_type_counts"] = dict(sorted(qa_type_counts.items()))
    metadata["expected_behavior_counts"] = dict(sorted(behavior_counts.items()))

    thresholds = _parse_thresholds(args.threshold)
    report = EvidenceRegressionReport(metadata=metadata, thresholds=thresholds)
    report.write(args.output_dir)
    print(report.to_markdown(), end="")
    return 0 if report.passed() else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m business.research.rag.run_evidence_eval",
        description="Write a paper RAG evidence benchmark summary/report from a golden set.",
    )
    parser.add_argument("--golden-set", required=True, help="Path to EvidenceQAPair JSON golden set.")
    parser.add_argument(
        "--output-dir",
        default=".newsroom/eval/evidence",
        help="Directory for evidence_regression_report.{json,md}.",
    )
    parser.add_argument(
        "--threshold",
        action="append",
        default=[],
        metavar="METRIC=VALUE",
        help="Optional threshold, for example retrieval.evidence_coverage=0.8.",
    )
    return parser


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
