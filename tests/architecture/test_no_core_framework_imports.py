from __future__ import annotations

import ast
from pathlib import Path

from tests.architecture._helpers import PROJECT_ROOT


SCAN_ROOTS = (
    "business",
    "framework",
    "infrastructure",
    "interfaces",
    "scripts",
    "tests",
)


def test_python_and_toml_do_not_reference_core_framework() -> None:
    violations: list[str] = []
    legacy_framework = "core" + ".framework"
    legacy_package = '"' + "core" + '"'
    for root_name in SCAN_ROOTS:
        root = PROJECT_ROOT / root_name
        if root.exists():
            violations.extend(_python_import_violations(root))

    pyproject = PROJECT_ROOT / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    if legacy_framework in text or legacy_package in text:
        violations.append(pyproject.relative_to(PROJECT_ROOT).as_posix())

    assert violations == []


def _python_import_violations(root: Path) -> list[str]:
    violations: list[str] = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "core" or alias.name.startswith("core."):
                        violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "core" or node.module.startswith("core."):
                    violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {node.module}")
    return violations
