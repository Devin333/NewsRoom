from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from backend.research.rag.evaluation.live_answer_readiness import (
    DEFAULT_GOLDEN_SET_PATH,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PAPERS_DIR,
    readiness_gate_exit_code,
    write_live_answer_readiness,
)


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = write_live_answer_readiness(
        output_dir=Path(args.output_dir),
        golden_set_path=Path(args.golden_set),
        papers_dir=Path(args.papers_dir),
    )
    print(json.dumps(result.payload, ensure_ascii=False, indent=2, sort_keys=True), end="\n")
    return readiness_gate_exit_code(
        result.payload,
        require_fixture=args.require_fixture,
        require_real_corpus=args.require_real_corpus,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend.research.rag.cli.check_live_answer_readiness",
        description="Write Paper RAG live answer eval readiness artifacts without network calls.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for readiness.json and readiness.md.",
    )
    parser.add_argument(
        "--golden-set",
        default=str(DEFAULT_GOLDEN_SET_PATH),
        help="EvidenceQAPair JSON golden set inspected for real-corpus readiness.",
    )
    parser.add_argument(
        "--papers-dir",
        default=str(DEFAULT_PAPERS_DIR),
        help="Directory containing per-paper research_document.json artifacts.",
    )
    parser.add_argument(
        "--require-fixture",
        action="store_true",
        help="Return non-zero when fixture live answer eval prerequisites are not ready.",
    )
    parser.add_argument(
        "--require-real-corpus",
        action="store_true",
        help="Return non-zero when real-corpus live answer eval prerequisites are not ready.",
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
