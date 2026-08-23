from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNNERS_ROOT = PROJECT_ROOT / "framework" / "harness"


def test_concrete_runner_modules_do_not_import_legacy_step_runner_shim() -> None:
    concrete_modules = {path for path in RUNNERS_ROOT.rglob("*.py")}
    violations: list[str] = []
    for path in concrete_modules:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "framework.workflow.runners.step_runner":
                violations.append(path.as_posix())
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "framework.workflow.runners.step_runner":
                        violations.append(path.as_posix())

    assert violations == []


def test_legacy_step_runner_module_is_removed() -> None:
    assert not any(path.name in {"step_runner.py", "_step_runner_impl.py"} for path in RUNNERS_ROOT.rglob("*.py"))
