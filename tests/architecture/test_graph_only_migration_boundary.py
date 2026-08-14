from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION_ROOT = _PROJECT_ROOT / "scripts/graph_only_migration"
_RUNTIME_ROOTS = (
    _PROJECT_ROOT / "business",
    _PROJECT_ROOT / "framework",
    _PROJECT_ROOT / "interfaces",
    _PROJECT_ROOT / "infrastructure",
)
_FORBIDDEN_MIGRATION_IMPORTS = (
    "business",
    "framework.agent.loop",
    "framework.harness.workflow",
    "framework.llm",
    "framework.memory",
    "framework.tool",
    "framework.workflow",
    "infrastructure",
    "interfaces",
)


def test_graph_only_migrator_does_not_import_live_or_legacy_runtime() -> None:
    violations: list[str] = []
    for path in sorted(_MIGRATION_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported: list[str] = []
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported = [node.module]
            for module_name in imported:
                if module_name.startswith(_FORBIDDEN_MIGRATION_IMPORTS):
                    violations.append(
                        f"{path.relative_to(_PROJECT_ROOT).as_posix()}:{node.lineno}:"
                        f"{module_name}"
                    )
    assert violations == []


def test_runtime_packages_do_not_import_migration_only_tooling() -> None:
    violations: list[str] = []
    for root in _RUNTIME_ROOTS:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module is not None:
                    names = [node.module]
                else:
                    continue
                for module_name in names:
                    if module_name.startswith("scripts.graph_only_migration"):
                        violations.append(
                            f"{path.relative_to(_PROJECT_ROOT).as_posix()}:"
                            f"{node.lineno}:{module_name}"
                        )
    assert violations == []


def test_importing_migrator_does_not_load_retired_runtime_in_fresh_process() -> None:
    command = (
        "import sys; import scripts.graph_only_migration; "
        "names=sorted(name for name in sys.modules "
        "if name == 'framework.workflow' "
        "or name.startswith('framework.workflow.') "
        "or name == 'framework.harness.workflow' "
        "or name.startswith('framework.harness.workflow.')); "
        "print('\\n'.join(names))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", command],
        cwd=_PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "\n"


def test_migration_only_tooling_has_no_writer_or_live_dispatch_surface() -> None:
    forbidden_function_names = {
        "apply_plan",
        "dispatch",
        "execute",
        "publish",
        "resume",
        "switch_pointer",
        "write",
    }
    violations: list[str] = []
    for path in sorted(_MIGRATION_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in forbidden_function_names:
                    violations.append(
                        f"{path.relative_to(_PROJECT_ROOT).as_posix()}:{node.lineno}:"
                        f"{node.name}"
                    )
    assert violations == []
