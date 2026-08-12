from __future__ import annotations

import ast
import tomllib
from pathlib import Path

from framework.llm.budget import (
    GLOBAL_BUDGET_COMPATIBILITY_EXPIRES_RELEASE,
    GLOBAL_BUDGET_COMPATIBILITY_INTRODUCED_RELEASE,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_ROOT = PROJECT_ROOT / "framework" / "governance" / "budget"
PRODUCTION_ROOTS = tuple(
    PROJECT_ROOT / name
    for name in ("business", "framework", "infrastructure", "interfaces")
)
FORBIDDEN_CANONICAL_IMPORTS = (
    "business",
    "framework.agent",
    "framework.workflow",
    "infrastructure",
    "interfaces",
)
COMPATIBILITY_MODULES = {
    "framework.agent.runtime.llm": {
        "framework/agent/runtime/llm.py",
        "framework/agent/runtime/__init__.py",
    },
    "framework.workflow.governance.budget": {
        "framework/workflow/__init__.py",
        "framework/workflow/governance/__init__.py",
        "framework/workflow/governance/budget.py",
    },
}
COMPATIBILITY_GLOBAL_NAMES = frozenset(
    {
        "GlobalBudgetCheck",
        "GlobalBudgetExceededError",
        "GlobalBudgetPolicy",
        "GlobalBudgetTracker",
        "GlobalBudgetUsage",
    }
)


def test_canonical_budget_owner_has_no_forbidden_layer_dependencies() -> None:
    violations: list[str] = []
    for path in CANONICAL_ROOT.rglob("*.py"):
        for imported in _imported_modules(path):
            if any(
                imported == prefix or imported.startswith(f"{prefix}.")
                for prefix in FORBIDDEN_CANONICAL_IMPORTS
            ):
                violations.append(
                    f"{path.relative_to(PROJECT_ROOT).as_posix()}: {imported}"
                )

    assert violations == []


def test_global_budget_types_have_one_implementation_owner() -> None:
    definitions: dict[str, list[str]] = {}
    for root in PRODUCTION_ROOTS:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name.startswith("GlobalBudget"):
                    definitions.setdefault(node.name, []).append(
                        path.relative_to(PROJECT_ROOT).as_posix()
                    )

    assert definitions == {
        "GlobalBudgetCheck": ["framework/llm/budget/tracker.py"],
        "GlobalBudgetExceededError": ["framework/llm/budget/tracker.py"],
        "GlobalBudgetGuard": ["framework/llm/budget/tracker.py"],
        "GlobalBudgetPolicy": ["framework/llm/budget/policy.py"],
        "GlobalBudgetTracker": ["framework/llm/budget/tracker.py"],
        "GlobalBudgetUsage": ["framework/llm/budget/tracker.py"],
    }


def test_production_does_not_consume_compatibility_budget_modules() -> None:
    violations: list[str] = []
    for root in PRODUCTION_ROOTS:
        for path in root.rglob("*.py"):
            relative = path.relative_to(PROJECT_ROOT).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or node.module is None:
                    continue
                allowed = COMPATIBILITY_MODULES.get(node.module)
                imported_names = {
                    alias.name
                    for alias in node.names
                    if alias.name in COMPATIBILITY_GLOBAL_NAMES or alias.name == "*"
                }
                if imported_names and allowed is not None and relative not in allowed:
                    violations.append(
                        f"{relative}: {node.module} imports {sorted(imported_names)}"
                    )

    assert violations == []


def test_compatibility_facade_has_one_release_expiry() -> None:
    pyproject = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    package_version = str(pyproject["project"]["version"])

    assert GLOBAL_BUDGET_COMPATIBILITY_INTRODUCED_RELEASE == package_version
    assert _minor_release(GLOBAL_BUDGET_COMPATIBILITY_EXPIRES_RELEASE) == (
        _minor_release(package_version)[0],
        _minor_release(package_version)[1] + 1,
    )
    tracker_source = (
        PROJECT_ROOT / "framework" / "llm" / "budget" / "tracker.py"
    ).read_text(encoding="utf-8")
    assert "self._usage" not in tracker_source


def _imported_modules(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    return tuple(imported)


def _minor_release(value: str) -> tuple[int, int]:
    parts = value.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise AssertionError(f"release must use major.minor.patch: {value}")
    return int(parts[0]), int(parts[1])
