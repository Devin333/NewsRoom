from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MEMORY_ROOT = PROJECT_ROOT / "core" / "framework" / "memory"
FORBIDDEN_IMPORT_PREFIXES = (
    "business",
    "interfaces",
    "workflows.daily_intelligence",
    "domain.reports",
    "evidence",
    "quality",
)


def test_framework_memory_does_not_import_business_or_interface_modules() -> None:
    violations: list[str] = []
    for path in MEMORY_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for imported in _imported_modules(tree):
            if _is_forbidden_import(imported):
                relative_path = path.relative_to(PROJECT_ROOT).as_posix()
                violations.append(f"{relative_path}: {imported}")

    assert violations == []


def _imported_modules(tree: ast.AST) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def _is_forbidden_import(module: str) -> bool:
    return any(
        module == prefix or module.startswith(f"{prefix}.")
        for prefix in FORBIDDEN_IMPORT_PREFIXES
    )
