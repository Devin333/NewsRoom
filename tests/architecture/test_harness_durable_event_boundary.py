from __future__ import annotations

import ast
from pathlib import Path


HARNESS_ROOT = Path("framework/harness")
CONTROL_PLANE = HARNESS_ROOT / "control_plane" / "harness.py"
DURABLE_ADAPTER = HARNESS_ROOT / "control_plane" / "durable_events.py"
PRODUCTION_ROOTS = tuple(
    Path(root) for root in ("business", "framework", "infrastructure", "interfaces", "scripts")
)


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
        "framework.harness.workers.adapters",
        "framework.harness.workers.fake",
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
    direct_worker_calls = [
        node
        for node in ast.walk(call_worker)
        if isinstance(node, ast.Call)
        and (
            isinstance(node.func, ast.Name)
            and node.func.id == "worker"
            or isinstance(node.func, ast.Attribute)
            and node.func.attr in {"execute", "generate", "run_skill", "run_subagent"}
        )
    ]
    assert direct_worker_calls
    called_attributes = {
        node.func.attr
        for node in ast.walk(call_worker)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert called_attributes.isdisjoint({"deliver", "dispatch", "publish", "subscribe"})


def test_research_runtime_requires_injected_harness_event_port() -> None:
    source = (
        Path("business")
        / "research"
        / "application"
        / "single_paper_runtime.py"
    ).read_text(encoding="utf-8")

    assert "InMemoryHarnessEventPort" not in source
    assert "event_port_factory" in source


def test_production_code_never_instantiates_in_memory_harness_event_port() -> None:
    violations: list[str] = []
    for path in _production_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node.func) == "InMemoryHarnessEventPort":
                violations.append(f"{path.as_posix()}:{node.lineno}")
    assert violations == []


def test_every_production_control_plane_composition_injects_event_port() -> None:
    compositions: list[str] = []
    missing_event_port: list[str] = []
    for path in _production_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _call_name(node.func) != "HarnessControlPlane":
                continue
            location = f"{path.as_posix()}:{node.lineno}"
            compositions.append(location)
            if not any(keyword.arg == "event_port" for keyword in node.keywords):
                missing_event_port.append(location)
    assert compositions
    assert missing_event_port == []


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return tuple(imports)


def _production_python_files() -> tuple[Path, ...]:
    return tuple(
        path
        for root in PRODUCTION_ROOTS
        if root.exists()
        for path in sorted(root.rglob("*.py"))
        if "tests" not in path.parts
    )


def _call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None
