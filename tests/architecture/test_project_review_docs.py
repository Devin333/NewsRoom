from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_prd1_is_marked_as_historical_review_snapshot() -> None:
    text = (PROJECT_ROOT / "docs" / "prd1.md").read_text(encoding="utf-8")

    assert text.startswith("# 历史审查快照")
    assert "project_review_report.md" in text
    assert "不再作为当前任务入口或完成状态依据" in text


def test_project_review_report_records_prd1_historical_status() -> None:
    text = (PROJECT_ROOT / "docs" / "project_review_report.md").read_text(encoding="utf-8")

    assert "`docs/prd1.md` 已标记为历史审查快照" in text
    assert "后续不要把它作为当前任务入口或完成状态依据" in text
