from __future__ import annotations

import ast
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_OWNER = _PROJECT_ROOT / "framework/harness/graph/operations.py"
_APPLICATION_SERVICE = _PROJECT_ROOT / "interfaces/services/harness_graph_service.py"
_WAIT_APPLICATION_SERVICE = _PROJECT_ROOT / "interfaces/services/harness_wait_service.py"
_FORBIDDEN_APPLICATION_IMPORTS = (
    "framework.workflow",
    "framework.harness.control_plane.durable_events",
    "infrastructure.storage",
    "interfaces.services.run_operation_service",
)


def test_graph_run_operation_owner_is_framework_only() -> None:
    tree = ast.parse(_OWNER.read_text(encoding="utf-8"), filename=str(_OWNER))

    assert [
        f"{node.lineno}:{module}"
        for node in ast.walk(tree)
        for module in _imported_modules(node)
        if module == "interfaces"
        or module.startswith("interfaces.")
        or module == "infrastructure"
        or module.startswith("infrastructure.")
        or module == "framework.workflow"
        or module.startswith("framework.workflow.")
    ] == []

    assert not (
        _PROJECT_ROOT / "framework/harness/control_plane/graph_operations.py"
    ).exists()


def test_graph_application_service_uses_ports_not_legacy_runtime_or_stores() -> None:
    tree = ast.parse(
        _APPLICATION_SERVICE.read_text(encoding="utf-8"),
        filename=str(_APPLICATION_SERVICE),
    )

    assert [
        f"{node.lineno}:{module}"
        for node in ast.walk(tree)
        for module in _imported_modules(node)
        if any(
            module == forbidden or module.startswith(f"{forbidden}.")
            for forbidden in _FORBIDDEN_APPLICATION_IMPORTS
        )
    ] == []


def test_graph_application_service_exposes_required_run_operations() -> None:
    tree = ast.parse(
        _APPLICATION_SERVICE.read_text(encoding="utf-8"),
        filename=str(_APPLICATION_SERVICE),
    )
    service = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "HarnessGraphApplicationService"
    )
    methods = {
        node.name
        for node in service.body
        if isinstance(node, ast.FunctionDef)
    }

    assert {"cancel_run", "inspect_run", "replay_run"}.issubset(methods)

    wait_tree = ast.parse(
        _WAIT_APPLICATION_SERVICE.read_text(encoding="utf-8"),
        filename=str(_WAIT_APPLICATION_SERVICE),
    )
    wait_service = next(
        node
        for node in wait_tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "HarnessWaitApplicationService"
    )
    wait_methods = {
        node.name
        for node in wait_service.body
        if isinstance(node, ast.FunctionDef)
    }
    assert {"deliver_signal", "decide_approval", "cancel_wait"}.issubset(
        wait_methods
    )
    submit = next(
        node
        for node in wait_service.body
        if isinstance(node, ast.FunctionDef) and node.name == "_submit"
    )
    called_methods = {
        node.func.attr
        for node in ast.walk(submit)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert {"accept_graph_wait_cause", "recover_and_run"}.issubset(called_methods)


def _imported_modules(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    if isinstance(node, ast.ImportFrom) and node.module is not None:
        return (node.module,)
    return ()
