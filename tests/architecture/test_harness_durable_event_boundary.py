from __future__ import annotations

import ast
from pathlib import Path


HARNESS_ROOT = Path("framework/harness")
CONTROL_PLANE = HARNESS_ROOT / "control_plane" / "harness.py"
DURABLE_ADAPTER = HARNESS_ROOT / "control_plane" / "durable_events.py"


def test_harness_framework_has_no_concrete_composition_dependency() -> None:
    violations: list[str] = []
    for path in sorted(HARNESS_ROOT.rglob("*.py")):
        for imported in _imports(path):
            if imported.split(".", 1)[0] in {"business", "infrastructure", "interfaces"}:
                violations.append(f"{path.as_posix()}: {imported}")
    assert violations == []


def test_event_adapter_cannot_decide_harness_flow_or_invoke_workers() -> None:
    tree = ast.parse(DURABLE_ADAPTER.read_text(encoding="utf-8"), filename=str(DURABLE_ADAPTER))
    forbidden_imports = (
        "framework.harness.control_plane.gates",
        "framework.harness.control_plane.routing",
        "framework.harness.control_plane.scheduler",
        "framework.harness.memory",
        "framework.harness.workers",
    )
    assert all(
        not imported.startswith(forbidden_imports)
        for imported in _imports(DURABLE_ADAPTER)
    )
    forbidden_calls = {
        "call_tool",
        "commit_write",
        "evaluate",
        "generate",
        "next_decision",
        "run_skill",
        "run_subagent",
    }
    called_attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert called_attributes.isdisjoint(forbidden_calls)


def test_control_plane_has_no_implicit_memory_fallback_or_subscriber_routing() -> None:
    source = CONTROL_PLANE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(CONTROL_PLANE))
    assert "event_port or InMemoryHarnessEventPort" not in source
    assert "framework.events.subscriber" not in _imports(CONTROL_PLANE)
    assert "framework.events.runtime.delivery" not in _imports(CONTROL_PLANE)

    event_port_assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
            and target.attr == "event_port"
            for target in node.targets
        )
    ]
    assert len(event_port_assignments) == 1
    assert isinstance(event_port_assignments[0].value, ast.Name)
    assert event_port_assignments[0].value.id == "event_port"

    call_worker = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_call_worker"
    )
    assert any(
        isinstance(node, ast.Call)
        and (
            isinstance(node.func, ast.Name)
            or isinstance(node.func, ast.Attribute)
        )
        for node in ast.walk(call_worker)
    )


def test_research_runtime_requires_injected_harness_event_port() -> None:
    source = (
        Path("business")
        / "research"
        / "application"
        / "single_paper_runtime.py"
    ).read_text(encoding="utf-8")

    assert "InMemoryHarnessEventPort" not in source
    assert "event_port_factory" in source


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return tuple(imports)
