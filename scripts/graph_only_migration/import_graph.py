"""Verify that history-only tooling is isolated from production composition.

The graph is intentionally small and source based.  It follows only imports
that can be resolved inside the repository, while separately rejecting known
runtime prefixes.  A history classifier therefore cannot become a hidden
worker, replay, resume, or side-effect entry point through a transitive import.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable


GRAPH_SCHEMA = "newsroom.graph-only-history-import-graph/v1"
HISTORY_PREFIX = "scripts.graph_only_migration"
PRODUCTION_ROOTS = (
    "framework",
    "backend",
    "interfaces",
    "infrastructure",
    "scripts",
)
FORBIDDEN_RUNTIME_PREFIXES = (
    "framework.workflow",
    "framework.harness.workflow",
    "framework.harness.control_plane",
    "framework.harness.context",
    "framework.harness.graph",
    "framework.harness.artifacts",
    "framework.harness.skills",
    "framework.harness.subagents",
    "framework.harness.runtime",
    "framework.harness.side_effects",
    "framework.harness.task_plan",
    "framework.harness.waits",
    "framework.harness.workers",
    "framework.agent",
    "framework.workers",
    "framework.events.application",
    "framework.events.runtime",
    "framework.memory",
    "framework.tool",
    "backend",
    "interfaces",
    "infrastructure",
)
HISTORY_RUNTIME_PREFIXES = (
    "framework.workflow",
    "framework.harness.workflow",
    "framework.harness.control_plane",
    "framework.harness.context",
    "framework.harness.graph",
    "framework.harness.artifacts",
    "framework.harness.skills",
    "framework.harness.subagents",
    "framework.harness.runtime",
    "framework.harness.side_effects",
    "framework.harness.task_plan",
    "framework.harness.waits",
    "framework.harness.workers",
    "framework.agent",
    "framework.workers",
    "framework.events.application",
    "framework.events.runtime",
    "framework.memory",
    "framework.tool",
)


@dataclass(frozen=True)
class ImportEdge:
    source: str
    target: str
    line: int
    category: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "line": self.line,
            "category": self.category,
        }


def build_import_graph(project_root: Path) -> dict[str, Any]:
    files = _source_files(project_root)
    module_paths = _module_paths(files)
    edges: list[ImportEdge] = []
    parse_failures: list[dict[str, Any]] = []

    for relative in files:
        path = project_root / relative
        module = _module_name(relative)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except (OSError, SyntaxError, UnicodeError) as exc:
            parse_failures.append(
                {
                    "path": relative,
                    "error": type(exc).__name__,
                }
            )
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported = [_resolve_from_import(module, node)]
            else:
                continue
            for target in imported:
                if not target:
                    continue
                category = _edge_category(
                    source=module,
                    target=target,
                    module_paths=module_paths,
                )
                if category is not None:
                    edges.append(
                        ImportEdge(
                            source=module,
                            target=target,
                            line=node.lineno,
                            category=category,
                        )
                    )

    edges = sorted(edges, key=lambda item: (item.source, item.line, item.target))
    violations = _find_violations(edges, module_paths)
    return {
        "schema": GRAPH_SCHEMA,
        "history_prefix": HISTORY_PREFIX,
        "production_roots": list(PRODUCTION_ROOTS),
        "forbidden_runtime_prefixes": list(FORBIDDEN_RUNTIME_PREFIXES),
        "files_scanned": files,
        "edges": [edge.to_dict() for edge in edges],
        "violations": [edge.to_dict() for edge in violations],
        "parse_failures": parse_failures,
        "summary": {
            "files_scanned": len(files),
            "edges_scanned": len(edges),
            "violations": len(violations),
            "parse_failures": len(parse_failures),
            "is_valid": not violations and not parse_failures,
        },
        "policy": {
            "history_tooling_is_read_only": True,
            "production_cannot_import_history_tooling": True,
            "history_tooling_cannot_import_production_roots": True,
            "history_tooling_cannot_reach_forbidden_runtime": True,
        },
    }


def write_import_graph(project_root: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(build_import_graph(project_root), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )


def _source_files(project_root: Path) -> list[str]:
    paths: list[str] = []
    for root_name in PRODUCTION_ROOTS:
        root = project_root / root_name
        if root.is_file():
            if root.suffix == ".py":
                paths.append(root.relative_to(project_root).as_posix())
            continue
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            relative = path.relative_to(project_root).as_posix()
            if "__pycache__" in path.parts:
                continue
            paths.append(relative)
    return sorted(set(paths))


def _module_paths(files: Iterable[str]) -> dict[str, str]:
    return {
        _module_name(relative): relative
        for relative in files
        if _module_name(relative)
    }


def _module_name(relative: str) -> str:
    path = relative[:-3] if relative.endswith(".py") else relative
    parts = path.split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _resolve_from_import(module: str, node: ast.ImportFrom) -> str:
    imported = node.module or ""
    if node.level == 0:
        return imported
    base = module.split(".")
    if base and base[-1] == "__init__":
        base = base[:-1]
    base = base[: max(0, len(base) - node.level + 1)]
    return ".".join([*base, imported]).strip(".")


def _edge_category(
    *,
    source: str,
    target: str,
    module_paths: dict[str, str],
) -> str | None:
    if _is_history(source) and _has_prefix(target, HISTORY_RUNTIME_PREFIXES):
        return "history_to_runtime"
    if _is_history(source) and _is_production_module(target):
        return "history_to_production"
    if _is_production_module(source) and _is_history(target):
        return "production_to_history"
    target_module = _best_local_module(target, module_paths)
    if target_module is not None:
        return "local"
    return None


def _find_violations(
    edges: list[ImportEdge],
    module_paths: dict[str, str],
) -> list[ImportEdge]:
    adjacency: dict[str, list[ImportEdge]] = {}
    for edge in edges:
        adjacency.setdefault(edge.source, []).append(edge)

    reachable: set[str] = set()
    pending = [module for module in module_paths if _is_history(module)]
    while pending:
        source = pending.pop()
        if source in reachable:
            continue
        reachable.add(source)
        for edge in adjacency.get(source, []):
            target = _best_local_module(edge.target, module_paths)
            if target is not None and target not in reachable:
                pending.append(target)

    violations = [
        edge
        for edge in edges
        if edge.category in {"history_to_production", "history_to_runtime", "production_to_history"}
        or (
            edge.source in reachable
            and (
                _is_production_module(edge.target)
                or _has_prefix(edge.target, FORBIDDEN_RUNTIME_PREFIXES)
            )
        )
    ]
    return sorted(
        set(violations),
        key=lambda item: (item.source, item.line, item.target, item.category),
    )


def _best_local_module(target: str, module_paths: dict[str, str]) -> str | None:
    candidates = [target]
    while "." in target:
        target = target.rsplit(".", 1)[0]
        candidates.append(target)
    return next((candidate for candidate in candidates if candidate in module_paths), None)


def _is_history(module: str) -> bool:
    return module == HISTORY_PREFIX or module.startswith(HISTORY_PREFIX + ".")


def _is_production_module(module: str) -> bool:
    return any(
        module == root or module.startswith(root + ".")
        for root in PRODUCTION_ROOTS
    ) and not _is_history(module)


def _has_prefix(value: str, prefixes: Iterable[str]) -> bool:
    return any(value == prefix or value.startswith(prefix + ".") for prefix in prefixes)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report = build_import_graph(args.project_root.resolve())
    if args.output is not None:
        args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
        args.output.resolve().write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["summary"]["is_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_import_graph", "write_import_graph", "main"]
