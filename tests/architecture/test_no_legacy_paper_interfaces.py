from __future__ import annotations

import ast
from pathlib import Path

from interfaces.api.app import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INTERFACES_ROOT = PROJECT_ROOT / "interfaces"


def test_legacy_paper_and_board_interface_files_are_removed() -> None:
    removed_paths = [
        INTERFACES_ROOT / "api" / "routers" / "papers.py",
        INTERFACES_ROOT / "api" / "routers" / "boards.py",
        INTERFACES_ROOT / "services" / "paper_service.py",
        INTERFACES_ROOT / "services" / "paper_ingest_service.py",
        INTERFACES_ROOT / "services" / "board_service.py",
        INTERFACES_ROOT / "services" / "daily_run_service.py",
        INTERFACES_ROOT / "services" / "weekly_run_service.py",
        INTERFACES_ROOT / "services" / "approval_resume_service.py",
    ]

    assert [path.relative_to(PROJECT_ROOT).as_posix() for path in removed_paths if path.exists()] == []


def test_interfaces_do_not_import_legacy_board_or_paper_services() -> None:
    forbidden_prefixes = (
        "backend.boards",
        "interfaces.services.paper",
        "interfaces.services.board_service",
        "interfaces.services.daily_run_service",
        "interfaces.services.weekly_run_service",
        "interfaces.services.approval_resume_service",
    )
    violations = []
    for path in INTERFACES_ROOT.rglob("*.py"):
        for imported in _imports_for_file(path):
            if any(imported == prefix or imported.startswith(f"{prefix}.") for prefix in forbidden_prefixes):
                violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {imported}")

    assert violations == []


def test_openapi_exposes_research_routes_and_removes_legacy_routes() -> None:
    schema = create_app(audit_emitter_factory=None).openapi()
    paths = set(schema["paths"])

    assert "/api/v1/research/papers/analyze" in paths
    assert "/api/v1/research/papers/{paper_id}/analysis" in paths
    assert "/api/v1/research/papers/{paper_id}/reader" in paths
    assert "/api/v1/research/papers/{paper_id}/ask" in paths
    assert "/api/v1/research/runs/{run_id}/trace" in paths
    assert not any(path.startswith("/api/v1/papers") for path in paths)
    assert not any(path.startswith("/api/v1/boards") for path in paths)
    assert "/api/v1/runs/daily" not in paths
    assert "/api/v1/runs/weekly" not in paths
    assert "/api/v1/schedules/daily" not in paths
    assert "/api/v1/schedules/papers/ingest" not in paths


def _imports_for_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules
