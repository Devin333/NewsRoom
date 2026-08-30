from __future__ import annotations

import ast
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_OWNER = _PROJECT_ROOT / "framework/harness/control_plane/node_output.py"
_ADAPTER = _PROJECT_ROOT / "framework/harness/runtime/node_output.py"
_EXECUTOR = _PROJECT_ROOT / "framework/harness/runtime/activity_executor.py"
_LIVE_ROOTS = (
    _PROJECT_ROOT / "backend",
    _PROJECT_ROOT / "interfaces",
    _PROJECT_ROOT / "infrastructure",
)
_REQUIRED_LIVE_RUNTIME_PATHS = {
    "backend/research/application/reader_repair_runtime.py",
    "backend/research/application/single_paper_runtime.py",
    "interfaces/composition/agent_loop_graph.py",
    "interfaces/services/agent_loop_graph_service.py",
    "interfaces/services/agent_loop_smoke_service.py",
}
_FORBIDDEN_OWNER_ROOTS = (
    "backend",
    "framework.workflow",
    "infrastructure",
    "interfaces",
)
_ADAPTER_NAME = "HarnessAdmittedGraphActivityOutputAdapter"
_EXECUTOR_NAME = "HarnessGraphPhysicalActivityExecutor"


def test_node_output_owner_and_adapter_do_not_depend_on_legacy_layers() -> None:
    violations: list[str] = []
    for path in (_OWNER, _ADAPTER, _EXECUTOR):
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
        _ADAPTER.read_text(encoding="utf-8"),
        filename=str(_ADAPTER),
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


def test_physical_executor_is_graph_native_and_does_not_call_legacy_dispatch() -> None:
    source = _EXECUTOR.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(_EXECUTOR))
    executor = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == _EXECUTOR_NAME
    )
    methods = {
        node.name
        for node in executor.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    legacy_dispatch_calls = [
        node
        for node in ast.walk(executor)
        if isinstance(node, ast.Attribute)
        and node.attr == "dispatch"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "implementation"
    ]

    assert {"dispatch", "execute"}.issubset(methods)
    assert legacy_dispatch_calls == []
    assert "framework.workflow" not in source
    assert "Artifact" not in source


def test_graph_node_output_runtime_is_active_only_in_owned_compositions() -> None:
    violations: list[str] = []
    approved: list[str] = []
    for root in _LIVE_ROOTS:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            if any(
                (
                    isinstance(node, ast.Name)
                    and node.id in {_ADAPTER_NAME, _EXECUTOR_NAME}
                )
                or (
                    isinstance(node, ast.Attribute)
                    and node.attr in {_ADAPTER_NAME, _EXECUTOR_NAME}
                )
                for node in ast.walk(tree)
            ):
                relative = path.relative_to(_PROJECT_ROOT).as_posix()
                if relative in _REQUIRED_LIVE_RUNTIME_PATHS:
                    approved.append(relative)
                else:
                    violations.append(relative)

    assert violations == []
    assert set(approved) == _REQUIRED_LIVE_RUNTIME_PATHS


def _imported_modules(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    if isinstance(node, ast.ImportFrom) and node.module is not None:
        return (node.module,)
    return ()
