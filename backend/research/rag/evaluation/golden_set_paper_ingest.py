from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from backend.research.rag.evaluation.paper_benchmark_ingest import (
    DocumentParser,
    PaperIngestReport,
    SourcePackageFetcher,
    ingest_benchmark_papers,
)
from backend.research.rag.evaluation.paper_evidence_eval import load_evidence_golden_set


DEFAULT_GOLDEN_SET_PATH = Path("data/eval/golden_set.json")
DEFAULT_PAPERS_DIR = Path(".newsroom/papers")
DEFAULT_MANIFEST_PATH = Path(".newsroom/eval/golden-set-paper-ingest-manifest.json")


@dataclass(frozen=True)
class GoldenSetPaperIngestReport:
    golden_set: Path
    papers_dir: Path
    manifest_path: Path | None
    golden_set_paper_ids: tuple[str, ...]
    existing_paper_ids: tuple[str, ...]
    missing_before_ingest: tuple[str, ...]
    selected_paper_ids: tuple[str, ...]
    ingest_report: PaperIngestReport | None = None

    @property
    def requested(self) -> int:
        return len(self.selected_paper_ids)

    @property
    def failed(self) -> int:
        return self.ingest_report.failed if self.ingest_report is not None else 0

    @property
    def succeeded(self) -> int:
        return self.ingest_report.succeeded if self.ingest_report is not None else 0

    @property
    def skipped(self) -> int:
        return self.ingest_report.skipped if self.ingest_report is not None else 0

    @property
    def missing_after_ingest(self) -> tuple[str, ...]:
        covered = set(self.existing_paper_ids)
        if self.ingest_report is None:
            return self.missing_before_ingest
        for item in self.ingest_report.items:
            if item.status in {"succeeded", "skipped"}:
                covered.add(item.paper_id)
        return tuple(pid for pid in self.golden_set_paper_ids if pid not in covered)

    def to_dict(self) -> dict[str, Any]:
        return {
            "golden_set": str(self.golden_set),
            "papers_dir": str(self.papers_dir),
            "manifest_path": str(self.manifest_path) if self.manifest_path else "",
            "golden_set_paper_ids": list(self.golden_set_paper_ids),
            "existing_paper_ids": list(self.existing_paper_ids),
            "missing_before_ingest": list(self.missing_before_ingest),
            "selected_paper_ids": list(self.selected_paper_ids),
            "requested": self.requested,
            "succeeded": self.succeeded,
            "skipped": self.skipped,
            "failed": self.failed,
            "missing_after_ingest": list(self.missing_after_ingest),
            "ingest_report": self.ingest_report.to_dict() if self.ingest_report is not None else None,
        }


def ingest_golden_set_papers(
    *,
    golden_set: str | Path = DEFAULT_GOLDEN_SET_PATH,
    papers_dir: str | Path = DEFAULT_PAPERS_DIR,
    manifest_path: str | Path | None = DEFAULT_MANIFEST_PATH,
    force: bool = False,
    max_papers: int | None = None,
    fetcher: SourcePackageFetcher | None = None,
    parser: DocumentParser | None = None,
    pdf_parser_backend: str | None = None,
    with_pdf_sidecar: bool = False,
    pdf_sidecar_mode: str = "missing",
    merge_pdf_visuals: bool = True,
) -> GoldenSetPaperIngestReport:
    golden_path = Path(golden_set)
    papers_path = Path(papers_dir)
    manifest = Path(manifest_path) if manifest_path is not None else None
    golden_ids = _golden_set_paper_ids(golden_path)
    existing_ids = _existing_research_document_paper_ids(papers_path)
    missing_before = tuple(pid for pid in golden_ids if pid not in existing_ids)
    selected = list(golden_ids if force else missing_before)
    if max_papers is not None:
        selected = selected[:max(0, max_papers)]

    ingest_report = None
    if selected:
        ingest_report = ingest_benchmark_papers(
            selected,
            papers_dir=papers_path,
            force=force,
            manifest_path=None,
            fetcher=fetcher,
            parser=parser,
            pdf_parser_backend=pdf_parser_backend,
            with_pdf_sidecar=with_pdf_sidecar,
            pdf_sidecar_mode=pdf_sidecar_mode,
            merge_pdf_visuals=merge_pdf_visuals,
        )
    report = GoldenSetPaperIngestReport(
        golden_set=golden_path,
        papers_dir=papers_path,
        manifest_path=manifest,
        golden_set_paper_ids=golden_ids,
        existing_paper_ids=existing_ids,
        missing_before_ingest=missing_before,
        selected_paper_ids=tuple(selected),
        ingest_report=ingest_report,
    )
    if manifest is not None:
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return report


def _golden_set_paper_ids(path: Path) -> tuple[str, ...]:
    pairs = load_evidence_golden_set(path)
    return tuple(sorted({pair.paper_id for pair in pairs}))


def _existing_research_document_paper_ids(papers_dir: Path) -> tuple[str, ...]:
    ids: set[str] = set()
    for document_path in sorted(papers_dir.glob("*/research_document.json")):
        try:
            payload = json.loads(document_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        paper_id = str(payload.get("paper_id") or document_path.parent.name).strip()
        if paper_id:
            ids.add(paper_id)
    return tuple(sorted(ids))


__all__ = [
    "DEFAULT_GOLDEN_SET_PATH",
    "DEFAULT_MANIFEST_PATH",
    "DEFAULT_PAPERS_DIR",
    "GoldenSetPaperIngestReport",
    "ingest_golden_set_papers",
]
