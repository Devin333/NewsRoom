"""Build or verify the content-addressed repository golden corpus snapshot."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.research.rag.evaluation.golden_corpus_snapshot import (
    DEFAULT_GOLDEN_CORPUS_SNAPSHOT_PATH,
    build_golden_corpus_snapshot,
    load_golden_corpus_snapshot,
    write_golden_corpus_snapshot,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the checked-in real-corpus subset used by golden-set CI tests."
    )
    parser.add_argument(
        "--golden-set", type=Path, default=Path("data/eval/golden_set.json")
    )
    parser.add_argument("--papers-dir", type=Path, default=Path(".newsroom/papers"))
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_GOLDEN_CORPUS_SNAPSHOT_PATH
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Rebuild in memory and fail unless the committed snapshot is byte-equivalent in meaning.",
    )
    args = parser.parse_args(argv)

    rebuilt = build_golden_corpus_snapshot(
        golden_set_path=args.golden_set,
        papers_dir=args.papers_dir,
    )
    if args.check:
        committed = load_golden_corpus_snapshot(
            args.output,
            golden_set_path=args.golden_set,
        )
        if rebuilt != committed:
            print(
                "golden corpus snapshot is stale; rebuild without --check",
                file=sys.stderr,
            )
            return 1
        print(
            f"golden corpus snapshot verified: {len(committed.chunks)} chunks, "
            f"{len(committed.source_documents)} documents"
        )
        return 0

    write_golden_corpus_snapshot(rebuilt, args.output)
    print(
        f"golden corpus snapshot written: {len(rebuilt.chunks)} chunks, "
        f"{len(rebuilt.source_documents)} documents -> {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
