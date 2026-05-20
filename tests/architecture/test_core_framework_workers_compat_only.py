from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CORE_WORKERS_ROOT = PROJECT_ROOT / "core" / "framework" / "workers"
ALLOWED_IMPORT_PREFIXES = (
    "framework.workers",
    "infrastructure.storage.workers",
)


def test_core_framework_workers_is_compatibility_only() -> None:
    violations: list[str] = []
    for path in CORE_WORKERS_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if _is_docstring(node):
                continue
            if _is_allowed_import(node):
                continue
            violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {type(node).__name__}")

    assert violations == []


def _is_docstring(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _is_allowed_import(node: ast.stmt) -> bool:
    if not isinstance(node, ast.ImportFrom) or not node.module:
        return False
    return any(
        node.module == prefix or node.module.startswith(f"{prefix}.")
        for prefix in ALLOWED_IMPORT_PREFIXES
    )
