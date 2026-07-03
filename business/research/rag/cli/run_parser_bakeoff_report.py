from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from business.research.rag.evaluation.paper_parser_bakeoff_report import (
    ParserArtifactInput,
    ParserBakeoffReportConfig,
    build_parser_bakeoff_report,
)


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_output()
    args = _build_parser().parse_args(argv)
    rag_reports = _parse_named_paths(args.rag_report)
    ingest_manifests = _parse_named_paths(args.ingest_manifest)
    inputs = tuple(
        ParserArtifactInput(
            name=name,
            papers_dir=path,
            rag_report_path=rag_reports.get(name),
            ingest_manifest_path=ingest_manifests.get(name),
        )
        for name, path in _parse_named_paths(args.parser).items()
    )
    if not inputs:
        raise ValueError("at least one --parser name=path entry is required")
    report = build_parser_bakeoff_report(ParserBakeoffReportConfig(
        inputs=inputs,
        output_json=Path(args.output_json),
        output_markdown=Path(args.output_markdown),
    ))
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), end="\n")
    return 0


def _configure_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m business.research.rag.cli.run_parser_bakeoff_report",
        description="Summarize parser-level and optional RAG-level metrics for parser bake-off artifacts.",
    )
    parser.add_argument(
        "--parser",
        action="append",
        default=[],
        metavar="NAME=DIR",
        help="Parser artifact directory containing per-paper research_document.json files.",
    )
    parser.add_argument(
        "--rag-report",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help="Optional benchmark_suite_report.json for a parser name.",
    )
    parser.add_argument(
        "--ingest-manifest",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help="Optional parser bake-off ingest manifest for requested/succeeded/failed counts.",
    )
    parser.add_argument(
        "--output-json",
        default=".newsroom/eval/parser-bakeoff-report.json",
    )
    parser.add_argument(
        "--output-markdown",
        default=".newsroom/eval/parser-bakeoff-report.md",
    )
    return parser


def _parse_named_paths(values: Sequence[str]) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for raw in values:
        if "=" not in raw:
            raise ValueError(f"expected NAME=PATH: {raw!r}")
        name, path = raw.split("=", 1)
        name = name.strip()
        if not name:
            raise ValueError(f"parser name is empty: {raw!r}")
        out[name] = Path(path.strip())
    return out


if __name__ == "__main__":
    raise SystemExit(main())
