from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CORE_MEMORY_ROOT = PROJECT_ROOT / "core" / "framework" / "memory"


def test_core_framework_memory_is_compatibility_only() -> None:
    violations: list[str] = []
    for path in CORE_MEMORY_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                continue
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("framework.memory"):
                continue
            violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {type(node).__name__}")

    assert violations == []
