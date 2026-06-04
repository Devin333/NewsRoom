from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUSINESS_ROOT = PROJECT_ROOT / "business"


def test_obsolete_board_scoring_and_evaluation_packages_are_removed() -> None:
    assert not (BUSINESS_ROOT / "boards").exists()
    assert not (BUSINESS_ROOT / "scoring").exists()
    assert not (BUSINESS_ROOT / "evaluation").exists()


def test_business_research_is_isolated_from_legacy_runtime_layers() -> None:
    violations = []
    for path in (BUSINESS_ROOT / "research").rglob("*.py"):
        for imported in _imports_for_file(path):
            if imported.startswith(("business.boards", "interfaces", "infrastructure")):
                violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {imported}")

    assert violations == []


def test_business_tools_register_real_connectors_from_signal_layer() -> None:
    imports = _imports_for_file(BUSINESS_ROOT / "tools.py")

    assert "business.layers.signal.connector_tools" in imports
    assert all(not imported.startswith("business.boards") for imported in imports)


def _imports_for_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules
