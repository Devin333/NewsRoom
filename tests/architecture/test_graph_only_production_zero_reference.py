from __future__ import annotations

from pathlib import Path

from scripts.graph_only_migration.zero_reference_scan import scan_production_roots
from tests.architecture._helpers import PROJECT_ROOT


def test_live_production_roots_have_zero_retired_workflow_references() -> None:
    report = scan_production_roots(PROJECT_ROOT)

    assert report["summary"]["is_valid"] is True
    assert report["summary"]["violations"] == 0
    assert report["summary"]["parse_failures"] == 0
    assert report["summary"]["by_category"] == {
        "import": 0,
        "export": 0,
        "schema_or_reflection": 0,
        "fallback": 0,
    }
    assert report["production_roots"] == [
        "scripts/dev.py",
        "interfaces/services",
        "infrastructure/research",
        "business/research",
    ]


def test_scanner_reports_import_export_schema_and_fallback(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "interfaces" / "services").mkdir(parents=True)
    (tmp_path / "infrastructure" / "research").mkdir(parents=True)
    (tmp_path / "business" / "research").mkdir(parents=True)
    (tmp_path / "scripts" / "dev.py").write_text(
        "from framework.workflow.runtime import WorkflowRunner\n",
        encoding="utf-8",
    )
    (tmp_path / "interfaces" / "services" / "service.py").write_text(
        "__all__ = ['WorkflowArtifact']\n",
        encoding="utf-8",
    )
    (tmp_path / "infrastructure" / "research" / "service.py").write_text(
        "SCHEMA = 'newsroom.workflow-event/v1'\n",
        encoding="utf-8",
    )
    (tmp_path / "business" / "research" / "service.py").write_text(
        "try:\n    import optional\nexcept ImportError:\n    optional = None\n",
        encoding="utf-8",
    )

    report = scan_production_roots(tmp_path)
    categories = {item["category"] for item in report["violations"]}

    assert report["summary"]["is_valid"] is False
    assert categories == {"import", "export", "schema_or_reflection", "fallback"}
