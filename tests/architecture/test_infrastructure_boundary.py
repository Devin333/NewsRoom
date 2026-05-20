from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INFRASTRUCTURE_ROOT = PROJECT_ROOT / "infrastructure"


def test_infrastructure_does_not_import_business_or_interfaces() -> None:
    violations: list[str] = []
    for path in INFRASTRUCTURE_ROOT.rglob("*.py"):
        for imported in _imports_for_file(path):
            if imported in {"business", "interfaces"} or imported.startswith(("business.", "interfaces.")):
                violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {imported}")

    assert violations == []


def _imports_for_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules
