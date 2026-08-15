from __future__ import annotations

import ast
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_OWNER = _PROJECT_ROOT / "framework/harness/control_plane/node_output.py"
_INACTIVE_ADAPTER = _PROJECT_ROOT / "framework/harness/runtime/node_output.py"
_LIVE_ROOTS = (
    _PROJECT_ROOT / "business",
    _PROJECT_ROOT / "interfaces",
    _PROJECT_ROOT / "infrastructure",
)
_FORBIDDEN_OWNER_ROOTS = (
    "business",
    "framework.workflow",
    "infrastructure",
    "interfaces",
)
_ADAPTER_NAME = "HarnessAdmittedGraphActivityOutputAdapter"


def test_node_output_owner_and_adapter_do_not_depend_on_legacy_layers() -> None:
    violations: list[str] = []
    for path in (_OWNER, _INACTIVE_ADAPTER):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            for module in _imported_modules(node):
                if any(
                    module == root or module.startswith(f"{root}.")
                    for root in _FORBIDDEN_OWNER_ROOTS
                ):
                    violations.append(f"{path.name}:{node.lineno}:{module}")

    assert violations == []


def test_node_output_lease_generation_is_owned_by_the_resource_port() -> None:
    tree = ast.parse(_OWNER.read_text(encoding="utf-8"), filename=str(_OWNER))
    resource_port = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "HarnessNodeOutputResourcePort"
    )
    acquire = next(
        node
        for node in resource_port.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "acquire_after_admission"
    )

    assert [argument.arg for argument in acquire.args.args] == [
        "self",
        "activity",
        "admission",
    ]
    assert "generation" not in {argument.arg for argument in acquire.args.args}


def test_node_output_adapter_is_not_a_live_graph_dispatcher() -> None:
    tree = ast.parse(
        _INACTIVE_ADAPTER.read_text(encoding="utf-8"),
        filename=str(_INACTIVE_ADAPTER),
    )
    adapter = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == _ADAPTER_NAME
    )
    methods = {
        node.name
        for node in adapter.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert "run" in methods
    assert "dispatch" not in methods
    assert "HarnessGraphActivityDispatcherPort" not in {
        base.id for base in adapter.bases if isinstance(base, ast.Name)
    }


def test_production_layers_do_not_activate_node_output_adapter_in_gate_a() -> None:
    violations: list[str] = []
    for root in _LIVE_ROOTS:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            if any(
                (
                    isinstance(node, ast.Name)
                    and node.id == _ADAPTER_NAME
                )
                or (
                    isinstance(node, ast.Attribute)
                    and node.attr == _ADAPTER_NAME
                )
                for node in ast.walk(tree)
            ):
                violations.append(str(path.relative_to(_PROJECT_ROOT)))

    assert violations == []


def _imported_modules(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    if isinstance(node, ast.ImportFrom) and node.module is not None:
        return (node.module,)
    return ()
