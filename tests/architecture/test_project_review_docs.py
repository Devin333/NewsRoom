from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PRD1_PATH = PROJECT_ROOT / "docs" / "prd1.md"
PROJECT_REVIEW_PATH = PROJECT_ROOT / "docs" / "project_review_report.md"


def test_historical_review_docs_are_absent_or_marked_historical() -> None:
    if not PRD1_PATH.exists() and not PROJECT_REVIEW_PATH.exists():
        return
    assert PRD1_PATH.exists() and PROJECT_REVIEW_PATH.exists()

    text = PRD1_PATH.read_text(encoding="utf-8")

    assert text.startswith("# 历史审查快照")
    assert "project_review_report.md" in text
    assert "不再作为当前任务入口或完成状态依据" in text


def test_project_review_report_records_prd1_historical_status() -> None:
    if not PROJECT_REVIEW_PATH.exists() and not PRD1_PATH.exists():
        return
    assert PRD1_PATH.exists() and PROJECT_REVIEW_PATH.exists()

    text = PROJECT_REVIEW_PATH.read_text(encoding="utf-8")

    assert "`docs/prd1.md` 已标记为历史审查快照" in text
    assert "后续不要把它作为当前任务入口或完成状态依据" in text
