"""AST scanner for retired workflow references in live production roots.

The scanner intentionally has a narrow root set.  Migration history, fixtures,
and tests are not evidence about the live caller boundary and are therefore not
included in this report.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Any, Iterable, Sequence


EVIDENCE_SCHEMA = "newsroom.graph-only-production-zero-reference/v1"
PRODUCTION_ROOTS = (
    "scripts/dev.py",
    "interfaces/services",
    "infrastructure/research",
    "business/research",
)
FORBIDDEN_IMPORT_PREFIXES = (
    "framework.workflow",
    "framework.harness.workflow",
)
FORBIDDEN_SYMBOLS = frozenset(
    {
        "AgentLoopStepRunner",
        "HarnessWorkflowGraphCompiler",
        "HarnessWorkflowSpec",
        "WorkflowArtifact",
        "WorkflowArtifactRef",
        "WorkflowEnvelope",
        "WorkflowEvent",
        "WorkflowExecutor",
        "WorkflowRunner",
    }
)
FORBIDDEN_SCHEMA_MARKERS = (
    "newsroom.workflow",
    "newsroom.harness-workflow",
    "workflow-checkpoint",
)
FALLBACK_EXCEPTION_NAMES = frozenset({"ImportError", "ModuleNotFoundError"})

# These are data/configuration details, not runtime authority.  They remain
# visible in evidence so a future scan cannot silently expand this exception.
ALLOWLISTED_REFERENCES = {
    "business/research/document/chunk_storage.py": {
        "workflow_id": "chunk metadata field; not a workflow runtime identity",
    },
    "business/research/rag/retrieval/policy_config.py": {
        "ModuleNotFoundError": "optional PyYAML dependency configuration guard",
    },
}


@dataclass(frozen=True)
class Reference:
    path: str
    line: int
    category: str
    value: str
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "line": self.line,
            "category": self.category,
            "value": self.value,
            "detail": self.detail,
        }


def scan_production_roots(project_root: Path) -> dict[str, Any]:
    """Return a deterministic, machine-readable zero-reference report."""

    violations: list[Reference] = []
    allowlisted: list[Reference] = []
    parse_failures: list[Reference] = []
    files = list(_python_files(project_root))
    for path in files:
        relative = path.relative_to(project_root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except (SyntaxError, UnicodeError) as exc:
            parse_failures.append(
                Reference(
                    relative,
                    int(getattr(exc, "lineno", 0) or 0),
                    "parse_failure",
                    type(exc).__name__,
                    str(exc),
                )
            )
            continue
        visitor = _ReferenceVisitor(
            relative,
            violations,
            allowlisted,
            _docstring_node_ids(tree),
        )
        visitor.visit(tree)

    violations.sort(key=_reference_key)
    allowlisted.sort(key=_reference_key)
    parse_failures.sort(key=_reference_key)
    by_category = {
        category: sum(item.category == category for item in violations)
        for category in (
            "import",
            "export",
            "schema_or_reflection",
            "fallback",
        )
    }
    return {
        "schema": EVIDENCE_SCHEMA,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "production_roots": list(PRODUCTION_ROOTS),
        "forbidden_import_prefixes": list(FORBIDDEN_IMPORT_PREFIXES),
        "forbidden_symbols": sorted(FORBIDDEN_SYMBOLS),
        "forbidden_schema_markers": list(FORBIDDEN_SCHEMA_MARKERS),
        "files_scanned": [path.relative_to(project_root).as_posix() for path in files],
        "summary": {
            "files_scanned": len(files),
            "violations": len(violations),
            "allowlisted_references": len(allowlisted),
            "parse_failures": len(parse_failures),
            "by_category": by_category,
            "is_valid": not violations and not parse_failures,
        },
        "violations": [item.as_dict() for item in violations],
        "allowlisted_references": [item.as_dict() for item in allowlisted],
        "parse_failures": [item.as_dict() for item in parse_failures],
    }


class _ReferenceVisitor(ast.NodeVisitor):
    def __init__(
        self,
        relative_path: str,
        violations: list[Reference],
        allowlisted: list[Reference],
        docstring_ids: set[int],
    ) -> None:
        self.relative_path = relative_path
        self.violations = violations
        self.allowlisted = allowlisted
        self._docstring_ids = docstring_ids

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._check_import(node.lineno, alias.name, alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if node.level:
            module = "." * node.level + module
        for alias in node.names:
            imported = f"{module}.{alias.name}" if module else alias.name
            self._check_import(node.lineno, imported, alias.name)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in FORBIDDEN_SYMBOLS:
                self._record(node.lineno, "export", target.id, "forbidden public symbol")
            if isinstance(target, ast.Name) and target.id == "__all__":
                self._check_all(node.value, node.lineno)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name) and node.target.id in FORBIDDEN_SYMBOLS:
            self._record(node.lineno, "export", node.target.id, "forbidden public symbol")
        if isinstance(node.target, ast.Name) and node.target.id == "__all__":
            self._check_all(node.value, node.lineno)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.name in FORBIDDEN_SYMBOLS:
            self._record(node.lineno, "export", node.name, "forbidden public symbol")
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node.name in FORBIDDEN_SYMBOLS:
            self._record(node.lineno, "export", node.name, "forbidden public symbol")
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        name = _exception_name(node.type)
        if name in FALLBACK_EXCEPTION_NAMES:
            detail = "legacy import fallback candidate"
            if self._is_allowlisted(name):
                self._allow(node.lineno, "fallback", name, detail)
            else:
                self._record(node.lineno, "fallback", name, detail)
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and id(node) not in self._docstring_ids:
            value = node.value
            marker = next(
                (marker for marker in FORBIDDEN_SCHEMA_MARKERS if marker in value),
                None,
            )
            if marker:
                self._record(
                    node.lineno,
                    "schema_or_reflection",
                    value,
                    f"forbidden schema/reflection marker: {marker}",
                )
            elif value == "workflow_id":
                if self._is_allowlisted(value):
                    self._allow(
                        node.lineno,
                        "schema_or_reflection",
                        value,
                        "workflow identity field in non-authoritative metadata",
                    )
                else:
                    self._record(
                        node.lineno,
                        "schema_or_reflection",
                        value,
                        "workflow identity field outside explicit metadata allowlist",
                    )
        self.generic_visit(node)

    def _check_import(self, line: int, imported: str, symbol: str) -> None:
        if any(
            imported == prefix or imported.startswith(f"{prefix}.")
            for prefix in FORBIDDEN_IMPORT_PREFIXES
        ):
            self._record(line, "import", imported, "retired workflow namespace import")
        if symbol in FORBIDDEN_SYMBOLS:
            self._record(line, "import", symbol, "retired workflow symbol import")

    def _check_all(self, value: ast.expr | None, line: int) -> None:
        try:
            exports = ast.literal_eval(value) if value is not None else None
        except (ValueError, TypeError, SyntaxError):
            return
        if not isinstance(exports, (list, tuple, set)):
            return
        for exported in exports:
            if isinstance(exported, str) and exported in FORBIDDEN_SYMBOLS:
                self._record(line, "export", exported, "forbidden __all__ symbol")

    def _is_allowlisted(self, value: str) -> bool:
        return value in ALLOWLISTED_REFERENCES.get(self.relative_path, {})

    def _record(self, line: int, category: str, value: str, detail: str) -> None:
        self.violations.append(Reference(self.relative_path, line, category, value, detail))

    def _allow(self, line: int, category: str, value: str, detail: str) -> None:
        self.allowlisted.append(Reference(self.relative_path, line, category, value, detail))


def _python_files(project_root: Path) -> Iterable[Path]:
    for root in PRODUCTION_ROOTS:
        path = project_root / root
        if path.is_file() and path.suffix == ".py":
            yield path
            continue
        if path.is_dir():
            yield from sorted(
                candidate
                for candidate in path.rglob("*.py")
                if "__pycache__" not in candidate.parts
                and not any(part.startswith("pytest-tmp-") for part in candidate.parts)
            )


def _docstring_node_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node,
            (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
        ):
            continue
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            ids.add(id(first.value))
    return ids


def _exception_name(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Tuple):
        for item in node.elts:
            name = _exception_name(item)
            if name in FALLBACK_EXCEPTION_NAMES:
                return name
    return None


def _reference_key(item: Reference) -> tuple[str, int, str, str]:
    return item.path, item.line, item.category, item.value


def _git_value(project_root: Path, expression: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *shlex.split(expression)],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return completed.stdout.strip() or None


def build_evidence(project_root: Path) -> dict[str, Any]:
    report = scan_production_roots(project_root)
    report["source_commit"] = _git_value(project_root, "rev-parse HEAD")
    report["source_tree"] = _git_value(project_root, "rev-parse HEAD^{tree}")
    report["scan_commands"] = [
        "python -m scripts.graph_only_migration.zero_reference_scan --output "
        "openspec/changes/graph-only-orchestration/evidence/production-zero-reference.json",
        "pytest -q tests/architecture/test_graph_only_production_zero_reference.py",
    ]
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    evidence = build_evidence(args.project_root.resolve())
    payload = json.dumps(evidence, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = args.output
        if not output.is_absolute():
            output = args.project_root / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 0 if evidence["summary"]["is_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
