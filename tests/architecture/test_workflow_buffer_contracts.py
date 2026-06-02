from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUSINESS_ROOT = PROJECT_ROOT / "business"

_BUFFER_RECEIVER_NAMES = {"buffer", "data_buffer", "workflow_buffer"}
_MUTATING_METHODS = {
    "append",
    "clear",
    "extend",
    "insert",
    "pop",
    "popitem",
    "remove",
    "reverse",
    "setdefault",
    "sort",
    "update",
}


def test_workflow_buffer_reads_are_not_mutated_in_place() -> None:
    violations: list[str] = []
    for path in BUSINESS_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in _MUTATING_METHODS:
                continue
            if _contains_buffer_read_call(node.func.value):
                violations.append(
                    f"{path.relative_to(PROJECT_ROOT).as_posix()}:{node.lineno} "
                    f"mutates buffer.read(...) with .{node.func.attr}()"
                )

    assert violations == []


def _contains_buffer_read_call(node: ast.AST) -> bool:
    if _is_buffer_read_call(node):
        return True
    if isinstance(node, ast.Attribute):
        return _contains_buffer_read_call(node.value)
    if isinstance(node, ast.Subscript):
        return _contains_buffer_read_call(node.value)
    return False


def _is_buffer_read_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if not isinstance(node.func, ast.Attribute):
        return False
    if node.func.attr != "read":
        return False
    receiver = node.func.value
    return isinstance(receiver, ast.Name) and receiver.id in _BUFFER_RECEIVER_NAMES
