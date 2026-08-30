from __future__ import annotations

from pathlib import Path

from scripts.graph_only_migration.import_graph import build_import_graph


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_history_import_graph_isolated_from_production_and_runtime() -> None:
    report = build_import_graph(PROJECT_ROOT)

    assert report["summary"]["is_valid"] is True
    assert report["summary"]["violations"] == 0
    assert report["summary"]["parse_failures"] == 0
    assert report["policy"] == {
        "history_tooling_is_read_only": True,
        "production_cannot_import_history_tooling": True,
        "history_tooling_cannot_import_production_roots": True,
        "history_tooling_cannot_reach_forbidden_runtime": True,
    }


def test_history_import_graph_rejects_direct_and_transitive_runtime_edges(
    tmp_path: Path,
) -> None:
    migration = tmp_path / "scripts" / "graph_only_migration"
    migration.mkdir(parents=True)
    (tmp_path / "framework" / "harness" / "control_plane").mkdir(parents=True)
    (tmp_path / "backend").mkdir(parents=True)
    (tmp_path / "interfaces").mkdir(parents=True)
    (tmp_path / "infrastructure").mkdir(parents=True)
    (tmp_path / "scripts").mkdir(exist_ok=True)
    (tmp_path / "backend" / "entry.py").write_text(
        "from scripts.graph_only_migration import reader\n",
        encoding="utf-8",
    )
    (migration / "__init__.py").write_text(
        "from framework.harness.control_plane import HarnessControlPlane\n"
        "from .reader import read\n",
        encoding="utf-8",
    )
    (migration / "reader.py").write_text(
        "from backend import models\n",
        encoding="utf-8",
    )
    report = build_import_graph(tmp_path)

    assert report["summary"]["is_valid"] is False
    assert {item["category"] for item in report["violations"]} == {
        "history_to_production",
        "history_to_runtime",
        "production_to_history",
    }
