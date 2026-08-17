from __future__ import annotations

import ast
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ARTIFACT_OWNER_MODULES = (
    "framework/agent/artifacts/runtime/manager.py",
    "infrastructure/research/artifact_port.py",
    "infrastructure/research/artifact_publication.py",
    "infrastructure/research/graph_artifact_lifecycle.py",
    "interfaces/composition/research.py",
    "interfaces/composition/research_graph_artifacts.py",
    "interfaces/services/artifact_service.py",
)
_LEGACY_MANIFEST_METHODS = frozenset(
    {
        "append_manifest_artifact",
        "create_run_manifest",
        "finalize_run_manifest",
        "read_run_manifest",
        "update_run_manifest",
    }
)
_INACTIVE_V2_MANIFEST_SYMBOLS = frozenset(
    {
        "GraphTerminalManifestV2",
        "build_graph_terminal_manifest_v2",
        "parse_graph_terminal_manifest_v2",
    }
)
_V2_MANIFEST_INACTIVE_ROOTS = (
    _PROJECT_ROOT / "business",
    _PROJECT_ROOT / "infrastructure",
    _PROJECT_ROOT / "interfaces",
    _PROJECT_ROOT / "framework" / "harness" / "control_plane",
)


def test_graph_artifact_owner_modules_do_not_import_workflow_runtime() -> None:
    violations: list[str] = []
    for relative_path in _ARTIFACT_OWNER_MODULES:
        path = _PROJECT_ROOT / relative_path
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported = [node.module]
            else:
                continue
            for module_name in imported:
                if module_name == "framework.workflow" or module_name.startswith(
                    "framework.workflow."
                ):
                    violations.append(f"{relative_path}:{node.lineno}:{module_name}")
    assert violations == []


def test_graph_artifact_owner_modules_do_not_call_legacy_manifest_helpers() -> None:
    violations: list[str] = []
    for relative_path in _ARTIFACT_OWNER_MODULES:
        path = _PROJECT_ROOT / relative_path
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in _LEGACY_MANIFEST_METHODS:
                violations.append(f"{relative_path}:{node.lineno}:{node.attr}")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                node.name in _LEGACY_MANIFEST_METHODS
            ):
                violations.append(f"{relative_path}:{node.lineno}:{node.name}")
    assert violations == []


def test_graph_terminal_manifest_v2_contract_is_not_activated() -> None:
    violations: list[str] = []
    for root in _V2_MANIFEST_INACTIVE_ROOTS:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            used_symbols = {
                node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
            } | {
                node.attr
                for node in ast.walk(tree)
                if isinstance(node, ast.Attribute)
            }
            activated = sorted(used_symbols.intersection(_INACTIVE_V2_MANIFEST_SYMBOLS))
            if activated:
                relative = path.relative_to(_PROJECT_ROOT).as_posix()
                violations.append(f"{relative}: {', '.join(activated)}")

    assert violations == []
