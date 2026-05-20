from __future__ import annotations

import ast

from tests.architecture._helpers import PROJECT_ROOT


LEGACY_TOP_LEVEL_DIRS = (
    "domain",
    "evidence",
    "quality",
    "sources",
    "storage",
    "workflows",
)

SCAN_ROOTS = (
    "business",
    "framework",
    "infrastructure",
    "interfaces",
    "scripts",
    "tests",
)


def test_legacy_top_level_directories_do_not_exist() -> None:
    existing = [
        directory
        for directory in LEGACY_TOP_LEVEL_DIRS
        if (PROJECT_ROOT / directory).exists()
    ]

    assert existing == []


def test_python_and_toml_do_not_import_legacy_top_level_packages() -> None:
    violations: list[str] = []
    for root_name in SCAN_ROOTS:
        root = PROJECT_ROOT / root_name
        if root.exists():
            violations.extend(_python_import_violations(root))

    pyproject = PROJECT_ROOT / "pyproject.toml"
    pyproject_text = pyproject.read_text(encoding="utf-8")
    for package_name in LEGACY_TOP_LEVEL_DIRS:
        if f'"{package_name}"' in pyproject_text or f'"{package_name}.' in pyproject_text:
            violations.append(f"{pyproject.relative_to(PROJECT_ROOT).as_posix()}: {package_name}")

    assert violations == []


def _python_import_violations(root) -> list[str]:
    violations: list[str] = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _is_legacy_import(alias.name):
                        violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if _is_legacy_import(node.module):
                    violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {node.module}")
    return violations


def _is_legacy_import(module: str) -> bool:
    return any(
        module == package_name or module.startswith(f"{package_name}.")
        for package_name in LEGACY_TOP_LEVEL_DIRS
    )
