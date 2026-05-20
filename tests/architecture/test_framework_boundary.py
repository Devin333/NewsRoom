from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRAMEWORK_ROOT = PROJECT_ROOT / "core" / "framework"
FORBIDDEN_PREFIXES = (
    "business",
    "domain",
    "sources",
    "workflows",
    "evidence",
    "quality",
    "interfaces",
)


def test_framework_does_not_import_business_modules() -> None:
    violations: list[str] = []
    for path in FRAMEWORK_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for imported in _imported_modules(tree):
            if any(imported == prefix or imported.startswith(f"{prefix}.") for prefix in FORBIDDEN_PREFIXES):
                violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {imported}")

    assert violations == []


def _imported_modules(tree: ast.AST) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules
