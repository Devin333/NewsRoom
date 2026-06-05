from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNNERS_ROOT = PROJECT_ROOT / "framework" / "workflow" / "runners"


def test_concrete_runner_modules_do_not_import_legacy_step_runner_shim() -> None:
    concrete_modules = {
        "agent_loop.py",
        "artifact.py",
        "function.py",
        "join.py",
        "memory.py",
        "parallel.py",
        "quality_gate.py",
        "router.py",
        "subworkflow.py",
        "tool.py",
        "tool_batch.py",
    }
    violations: list[str] = []
    for filename in concrete_modules:
        path = RUNNERS_ROOT / filename
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "framework.workflow.runners.step_runner":
                violations.append(filename)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "framework.workflow.runners.step_runner":
                        violations.append(filename)

    assert violations == []


def test_legacy_step_runner_module_is_removed() -> None:
    assert not (RUNNERS_ROOT / "step_runner.py").exists()
    assert not (RUNNERS_ROOT / "_step_runner_impl.py").exists()
