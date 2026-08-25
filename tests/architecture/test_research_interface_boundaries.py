from __future__ import annotations

import ast
from collections import deque
from pathlib import Path

from tests.architecture._helpers import PROJECT_ROOT, matches_prefix


# These are the six Research/MCP surfaces that are part of the entrypoint
# parity contract.  The composition root is checked separately below.
RESEARCH_ENTRY_SURFACES = {
    "http_research": PROJECT_ROOT / "interfaces" / "api" / "routers" / "research.py",
    "http_mcp": PROJECT_ROOT / "interfaces" / "api" / "routers" / "mcp.py",
    "mcp_application": PROJECT_ROOT / "interfaces" / "services" / "mcp_service.py",
    "mcp_server": PROJECT_ROOT / "interfaces" / "mcp" / "server.py",
    "mcp_stdio": PROJECT_ROOT / "interfaces" / "mcp" / "stdio_server.py",
    "mcp_cli": PROJECT_ROOT / "interfaces" / "cli" / "commands" / "mcp.py",
}

MCP_INBOUND_MODULES = {
    "interfaces.api.routers.mcp",
    "interfaces.services.mcp_service",
    "interfaces.mcp",
    "interfaces.mcp.models",
    "interfaces.mcp.server",
    "interfaces.mcp.stdio_server",
    "interfaces.cli.commands.mcp",
}
MCP_OUTBOUND_MODULE = "framework.tool.runtime.mcp_adapter"
MCP_INBOUND_IMPORT_PREFIXES = (
    "interfaces.api.routers.mcp",
    "interfaces.services.mcp_service",
    "interfaces.mcp",
    "interfaces.cli.commands.mcp",
)

# Domain/runtime implementations are deliberately listed by ownership.  A
# broad ``infrastructure`` or ``framework`` ban would reject harmless policy
# and error modules and would make the boundary test unexplainable.
FORBIDDEN_RESEARCH_IMPORT_PREFIXES = (
    "business.research.application",
    "business.research.ports",
    "framework.harness",
    "framework.tool.runtime",
    "framework.workflow.runners",
    "framework.workflow.runtime.executor",
    "framework.workflow.runtime.runner",
    "infrastructure.research",
    "infrastructure.storage.artifacts",
    "infrastructure.storage.local_json",
    "infrastructure.storage.persistence.repository",
    "infrastructure.storage.postgres.repository",
    "infrastructure.storage.postgres.paper_chunk_repository",
    "infrastructure.storage.postgres.repair_memory_repository",
    "framework.agent.artifacts.stores",
    "interfaces.services.paper_rag_service",
    "interfaces.services.paper_rag_factory",
    "interfaces.services.paper_rag_transcript_store",
)

# A direct call through one of these owners is a bypass even when a future
# change hides the concrete class behind an alias or a local import.
FORBIDDEN_OWNER_SEGMENTS = {
    "artifact_port",
    "artifact_store",
    "executor",
    "harness",
    "repo",
    "repository",
    "run_store",
    "runtime",
    "store",
}
FORBIDDEN_CONSTRUCTOR_SUFFIXES = (
    "Executor",
    "Repository",
    "RunStore",
    "ArtifactPort",
    "ArtifactStore",
    "HarnessController",
    "Runtime",
)
FORBIDDEN_RESEARCH_RUNTIME_CALLS = {
    "ResearchApplicationService",
    "ResearchRuntimeProvider",
    "build_research_runtime_composition",
    "default_research_runtime_provider",
}
FORBIDDEN_OWNER_SUFFIXES = (
    "_artifact_port",
    "_artifact_store",
    "_executor",
    "_repository",
    "_run_store",
    "_runtime",
)
RESEARCH_OPERATIONS = {
    "analyze_paper",
    "ask_paper",
    "get_analysis",
    "get_reader",
    "get_trace",
}

EXPECTED_RESEARCH_GATEWAYS = {
    "http_research": {"services.research_service_factory"},
    "mcp_application": {"self.research_service_factory"},
}
APPROVED_COMPOSITION_IMPORTS = {
    "mcp_application": {
        "build_research_application_service",
        "default_source_runtime_provider",
    },
}

LEGACY_RESEARCH_SINGLETON_NAMES = {
    "_RAG_SERVICE",
    "_RESEARCH_SERVICE",
    "_DEFAULT_RESEARCH_SERVICE",
    "_RESEARCH_RUNTIME",
    "_DEFAULT_RESEARCH_RUN_STORE",
    "_RESEARCH_RUN_STORE",
}
COMPOSITION_SINGLETON_NAME = "_DEFAULT_RESEARCH_RUNTIME_PROVIDER"

# These are the two explicit Research-to-Harness child-session adapters from
# the production-composition design. Ordinary application/services modules
# may consume their public behavior, but may not assemble another controller.
DESIGNATED_RAG_CONSTRUCTORS = {
    "RAGSessionSpec": (
        "business.research.services.rag_policy",
        "framework.harness.rag.models",
    ),
    "BoundedRAGSessionController": (
        "business.research.application.paper_rag_session",
        "framework.harness.rag.session",
    ),
}
RAG_CONSTRUCTOR_EXPORT_MODULES = {
    "framework.harness",
    "framework.harness.rag",
    *{
        owner
        for _module, owner in DESIGNATED_RAG_CONSTRUCTORS.values()
    },
}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _module_name(path: Path) -> str:
    relative = path.relative_to(PROJECT_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports(path: Path) -> list[str]:
    """Return imports, including imports nested in functions."""

    modules: list[str] = []
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                package = list(path.relative_to(PROJECT_ROOT).parent.parts)
                keep = len(package) - node.level + 1
                base = package[: max(keep, 0)]
                if node.module:
                    modules.append(".".join((*base, *node.module.split("."))))
                else:
                    modules.extend(".".join((*base, alias.name)) for alias in node.names)
            elif node.module:
                modules.append(node.module)
        elif (
            isinstance(node, ast.Call)
            and _qualified_name(node.func)
            in {"import_module", "importlib.import_module", "__import__"}
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            modules.append(node.args[0].value)
    return modules


def _composition_imported_names(path: Path) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.ImportFrom) and node.level == 0:
            if node.module == "interfaces.composition.research":
                imported.update(alias.name for alias in node.names)
            elif node.module == "interfaces.composition":
                imported.update(
                    alias.name
                    for alias in node.names
                    if "research" in alias.name.casefold()
                )
        elif isinstance(node, ast.Import):
            if any(
                alias.name == "interfaces.composition.research"
                for alias in node.names
            ):
                imported.add("*")
    return imported


def _qualified_parts(node: ast.AST) -> tuple[str, ...]:
    """Extract a call's symbolic receiver without evaluating the source."""

    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        return (*_qualified_parts(node.value), node.attr)
    if isinstance(node, ast.Call):
        return _qualified_parts(node.func)
    if isinstance(node, ast.Subscript):
        return _qualified_parts(node.value)
    return ()


def _qualified_name(node: ast.AST) -> str:
    return ".".join(_qualified_parts(node))


def _is_forbidden_call(node: ast.Call) -> bool:
    parts = _qualified_parts(node.func)
    if not parts:
        return False
    terminal = parts[-1]
    if terminal in FORBIDDEN_RESEARCH_RUNTIME_CALLS:
        return True
    if terminal.endswith(FORBIDDEN_CONSTRUCTOR_SUFFIXES):
        return True
    # Only inspect symbolic receiver segments.  This avoids treating strings
    # such as ``"event store unavailable"`` as a storage access.
    for part in parts[:-1]:
        normalized = part.casefold().strip("_")
        if normalized in FORBIDDEN_OWNER_SEGMENTS:
            return True
        if normalized.endswith(FORBIDDEN_OWNER_SUFFIXES):
            return True
    return False


def _research_operation_calls(path: Path) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in RESEARCH_OPERATIONS
    ]


def test_research_entry_surfaces_use_application_boundaries() -> None:
    violations: list[str] = []
    for surface, path in RESEARCH_ENTRY_SURFACES.items():
        for imported in _imports(path):
            if matches_prefix(imported, FORBIDDEN_RESEARCH_IMPORT_PREFIXES):
                violations.append(f"{surface}:{path.name} imports {imported}")

        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Call) and _is_forbidden_call(node):
                violations.append(
                    f"{surface}:{path.name}:{node.lineno} calls {_qualified_name(node.func)}"
                )

        composition_imports = _composition_imported_names(path)
        if composition_imports != APPROVED_COMPOSITION_IMPORTS.get(surface, set()):
            violations.append(
                f"{surface}:{path.name} composition imports {sorted(composition_imports)}"
            )

    assert violations == []


def test_research_operations_have_only_the_approved_gateway() -> None:
    violations: list[str] = []
    for surface, path in RESEARCH_ENTRY_SURFACES.items():
        calls = _research_operation_calls(path)
        allowed = EXPECTED_RESEARCH_GATEWAYS.get(surface, set())
        for call in calls:
            receiver = _qualified_name(call.func.value)
            if receiver not in allowed:
                violations.append(
                    f"{surface}:{path.name}:{call.lineno} uses {receiver}.{call.func.attr}"
                )

        if surface in EXPECTED_RESEARCH_GATEWAYS and not calls:
            violations.append(f"{surface}:{path.name} has no Research application call")

    assert violations == []


def _resolve_local_import(module: str, modules: set[str]) -> str | None:
    if module in modules:
        return module
    pieces = module.split(".")
    for end in range(len(pieces) - 1, 0, -1):
        candidate = ".".join(pieces[:end])
        if candidate in modules:
            return candidate
    return None


def _mcp_graph_module_paths() -> dict[str, Path]:
    paths = {
        *(PROJECT_ROOT / "interfaces").rglob("*.py"),
        *(PROJECT_ROOT / "framework" / "tool").rglob("*.py"),
    }
    return {_module_name(path): path for path in paths}


def _local_import_graph(module_paths: dict[str, Path]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {module: set() for module in module_paths}
    available_modules = set(module_paths)
    for module, path in module_paths.items():
        for imported in _imports(path):
            resolved = _resolve_local_import(imported, available_modules)
            if resolved is not None:
                graph[module].add(resolved)
    return graph


def _cycle_path(graph: dict[str, set[str]], nodes: set[str]) -> list[str] | None:
    """Return one cycle in the induced boundary graph, if any."""

    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        state[node] = 1
        stack.append(node)
        for child in sorted(graph.get(node, ()) & nodes):
            if state.get(child, 0) == 0:
                cycle = visit(child)
                if cycle:
                    return cycle
            elif state[child] == 1:
                start = stack.index(child)
                return [*stack[start:], child]
        stack.pop()
        state[node] = 2
        return None

    for node in sorted(nodes):
        if state.get(node, 0) == 0:
            cycle = visit(node)
            if cycle:
                return cycle
    return None


def _reachable(graph: dict[str, set[str]], starts: set[str]) -> set[str]:
    reached = set(starts)
    queue = deque(starts)
    while queue:
        current = queue.popleft()
        for child in graph.get(current, ()):
            if child not in reached:
                reached.add(child)
                queue.append(child)
    return reached


def _reverse_graph(graph: dict[str, set[str]]) -> dict[str, set[str]]:
    reversed_graph: dict[str, set[str]] = {module: set() for module in graph}
    for source, targets in graph.items():
        for target in targets:
            reversed_graph[target].add(source)
    return reversed_graph


def test_mcp_inbound_and_outbound_adapter_are_separate_acyclic_graphs() -> None:
    modules = _mcp_graph_module_paths()
    graph = _local_import_graph(modules)
    inbound = {
        module
        for module in modules
        if module in MCP_INBOUND_MODULES or module.startswith("interfaces.mcp.")
    }
    outbound = {MCP_OUTBOUND_MODULE}

    assert MCP_INBOUND_MODULES <= inbound
    assert outbound <= set(modules)

    direct_cross_edges = sorted(
        [
            f"{source} -> {imported}"
            for source in inbound
            for imported in _imports(modules[source])
            if matches_prefix(imported, (MCP_OUTBOUND_MODULE,))
        ]
        + [
            f"{MCP_OUTBOUND_MODULE} -> {imported}"
            for imported in _imports(modules[MCP_OUTBOUND_MODULE])
            if matches_prefix(imported, MCP_INBOUND_IMPORT_PREFIXES)
        ]
    )
    assert direct_cross_edges == []

    inbound_reachable = _reachable(graph, inbound)
    outbound_reachable = _reachable(graph, outbound)
    assert not (inbound_reachable & outbound), (
        "MCP inbound reaches outbound adapter: "
        + ", ".join(sorted(inbound_reachable & outbound))
    )
    assert not (outbound_reachable & inbound), (
        "MCP outbound reaches inbound surface: "
        + ", ".join(sorted(outbound_reachable & inbound))
    )

    reverse_graph = _reverse_graph(graph)
    # Restrict cycle detection to SCC closures anchored at either transport
    # boundary.  This still catches recursion through intermediate local
    # modules while excluding an unrelated cycle in a leaf capability.
    cycle_scope = (
        inbound_reachable & _reachable(reverse_graph, inbound)
    ) | (
        outbound_reachable & _reachable(reverse_graph, outbound)
    )
    cycle = _cycle_path(graph, cycle_scope)
    assert cycle is None, "MCP boundary import cycle: " + " -> ".join(cycle or ())


def _module_level_assignments(tree: ast.Module) -> list[tuple[str, ast.AST, int]]:
    assignments: list[tuple[str, ast.AST, int]] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                assignments.append((target.id, value, node.lineno))
    return assignments


def _is_type_alias(value: ast.AST) -> bool:
    if isinstance(value, ast.Subscript) and isinstance(value.value, ast.Name):
        return value.value.id in {"Callable", "Type", "type"}
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
        return value.func.id in {"TypeVar", "NewType"}
    return False


def _looks_mutable_singleton(name: str, value: ast.AST) -> bool:
    lowered = name.casefold()
    role_name = any(token in lowered for token in ("service", "runtime", "store"))
    if not role_name or _is_type_alias(value):
        return False
    # A ``None`` placeholder is included: it is commonly populated lazily and
    # is still module-owned request/runtime state.
    return not isinstance(value, (ast.Constant, ast.Tuple)) or (
        isinstance(value, ast.Constant) and value.value is None
    )


def test_research_entrypoints_have_no_unowned_mutable_singletons() -> None:
    singleton_violations: list[str] = []
    scanned_paths = dict(RESEARCH_ENTRY_SURFACES)
    scanned_paths["composition"] = PROJECT_ROOT / "interfaces" / "composition" / "research.py"

    for surface, path in scanned_paths.items():
        for name, value, line in _module_level_assignments(_tree(path)):
            if name in LEGACY_RESEARCH_SINGLETON_NAMES:
                singleton_violations.append(f"{surface}:{path.name}:{line} legacy {name}")
                continue
            if _looks_mutable_singleton(name, value):
                if not (
                    surface == "composition"
                    and name == COMPOSITION_SINGLETON_NAME
                ):
                    singleton_violations.append(
                        f"{surface}:{path.name}:{line} unowned mutable {name}"
                    )

    assert singleton_violations == []

    composition_path = scanned_paths["composition"]
    composition_tree = _tree(composition_path)
    provider_assignments = {
        name: value
        for name, value, _line in _module_level_assignments(composition_tree)
        if name == COMPOSITION_SINGLETON_NAME
    }
    assert set(provider_assignments) == {COMPOSITION_SINGLETON_NAME}
    provider_value = provider_assignments[COMPOSITION_SINGLETON_NAME]
    assert isinstance(provider_value, ast.Call)
    assert _qualified_name(provider_value.func) == "ResearchRuntimeProvider"

    provider_classes = [
        node
        for node in composition_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ResearchRuntimeProvider"
    ]
    assert len(provider_classes) == 1
    lifecycle_methods = {
        node.name
        for node in provider_classes[0].body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert {"reset", "close"} <= lifecycle_methods


def _absolute_import_from(path: Path, node: ast.ImportFrom) -> str:
    if not node.level:
        return node.module or ""
    package = list(path.relative_to(PROJECT_ROOT).parent.parts)
    keep = len(package) - node.level + 1
    base = package[: max(keep, 0)]
    if node.module:
        base.extend(node.module.split("."))
    return ".".join(base)


def _rag_import_bindings(
    path: Path,
) -> tuple[
    dict[str, tuple[str, str]],
    dict[str, str],
    set[str],
    list[str],
]:
    symbol_bindings: dict[str, tuple[str, str]] = {}
    module_bindings: dict[str, str] = {}
    imported_modules: set[str] = set()
    violations: list[str] = []
    tree = _tree(path)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)
                local_name = alias.asname or alias.name.split(".", 1)[0]
                module_bindings[local_name] = alias.name if alias.asname else local_name
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        imported_from = _absolute_import_from(path, node)
        for alias in node.names:
            if alias.name == "*":
                if imported_from in RAG_CONSTRUCTOR_EXPORT_MODULES:
                    violations.append(
                        f"{_module_name(path)}:{node.lineno} uses ambiguous star import "
                        f"from {imported_from}"
                    )
                continue

            imported_symbol = f"{imported_from}.{alias.name}"
            imported_modules.add(imported_symbol)
            local_name = alias.asname or alias.name
            if alias.name in DESIGNATED_RAG_CONSTRUCTORS:
                symbol_bindings[local_name] = (alias.name, imported_from)
                canonical_owner = DESIGNATED_RAG_CONSTRUCTORS[alias.name][1]
                if imported_from != canonical_owner:
                    violations.append(
                        f"{_module_name(path)}:{node.lineno} imports {alias.name} "
                        f"from {imported_from}; expected {canonical_owner}"
                    )
            else:
                module_bindings[local_name] = imported_symbol

    # Preserve simple module-level constructor aliases without treating a
    # same-named local function as the Harness contract.
    changed = True
    while changed:
        changed = False
        for node in tree.body:
            if isinstance(node, ast.Assign):
                targets = node.targets
                value = node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets = [node.target]
                value = node.value
            else:
                continue
            if (
                isinstance(value, ast.Call)
                and _qualified_name(value.func)
                in {"import_module", "importlib.import_module", "__import__"}
                and value.args
                and isinstance(value.args[0], ast.Constant)
                and isinstance(value.args[0].value, str)
            ):
                imported_module = value.args[0].value
                imported_modules.add(imported_module)
                for target in targets:
                    if isinstance(target, ast.Name):
                        module_bindings[target.id] = imported_module
                continue
            resolved = _resolve_rag_constructor(
                value,
                symbol_bindings=symbol_bindings,
                module_bindings=module_bindings,
                imported_modules=imported_modules,
            )
            if resolved is None:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and symbol_bindings.get(target.id) != resolved:
                    symbol_bindings[target.id] = resolved
                    changed = True

    return symbol_bindings, module_bindings, imported_modules, violations


def _resolve_rag_constructor(
    node: ast.AST,
    *,
    symbol_bindings: dict[str, tuple[str, str]],
    module_bindings: dict[str, str],
    imported_modules: set[str],
) -> tuple[str, str] | None:
    parts = _qualified_parts(node)
    if not parts:
        return None
    if len(parts) == 1:
        return symbol_bindings.get(parts[0])

    constructor = parts[-1]
    if constructor not in DESIGNATED_RAG_CONSTRUCTORS:
        return None
    prefix_parts = list(parts[:-1])
    bound_module = module_bindings.get(prefix_parts[0])
    if bound_module is not None:
        prefix_parts = [bound_module, *prefix_parts[1:]]
    imported_from = ".".join(prefix_parts)
    if not any(
        imported_from == imported
        or imported_from.startswith(f"{imported}.")
        for imported in imported_modules
    ):
        return None
    return constructor, imported_from


def test_research_has_only_designated_rag_spec_and_controller_builders() -> None:
    observed: dict[str, list[tuple[str, int, str]]] = {
        name: [] for name in DESIGNATED_RAG_CONSTRUCTORS
    }
    violations: list[str] = []
    for path in (PROJECT_ROOT / "business" / "research").rglob("*.py"):
        (
            symbol_bindings,
            module_bindings,
            imported_modules,
            import_violations,
        ) = _rag_import_bindings(path)
        violations.extend(import_violations)
        module = _module_name(path)
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.Call):
                continue
            resolved = _resolve_rag_constructor(
                node.func,
                symbol_bindings=symbol_bindings,
                module_bindings=module_bindings,
                imported_modules=imported_modules,
            )
            if resolved is None:
                continue
            constructor, imported_from = resolved
            observed[constructor].append((module, node.lineno, imported_from))

    for constructor, (
        expected_module,
        expected_import_owner,
    ) in DESIGNATED_RAG_CONSTRUCTORS.items():
        calls = observed[constructor]
        call_contracts = {
            (module, imported_from)
            for module, _line, imported_from in calls
        }
        expected_contract = {(expected_module, expected_import_owner)}
        if call_contracts != expected_contract or len(calls) != 1:
            rendered = ", ".join(
                f"{module}:{line} via {imported_from}"
                for module, line, imported_from in sorted(calls)
            )
            violations.append(
                f"{constructor} expected once in {expected_module} via "
                f"{expected_import_owner}; observed {rendered}"
            )

    assert violations == []
