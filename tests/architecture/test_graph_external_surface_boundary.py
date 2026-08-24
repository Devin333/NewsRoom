from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SURFACE_ROOTS = (
    PROJECT_ROOT / "interfaces" / "api",
    PROJECT_ROOT / "interfaces" / "cli",
    PROJECT_ROOT / "interfaces" / "mcp",
    PROJECT_ROOT / "interfaces" / "sdk",
    PROJECT_ROOT / "sdk" / "python",
)
CLIENT_SURFACE_ROOTS = (
    PROJECT_ROOT / "apps" / "web" / "src",
    PROJECT_ROOT / "frontend" / "src" / "features" / "studio" / "review",
)
FORBIDDEN_PUBLIC_TOKENS = (
    "/api/v1/approvals",
    "news.approval.",
    "client.approvals",
    "resume_context",
    "resume-workflow",
    "buffer_updates",
    "node_updates",
    "resume_metadata",
)
FORBIDDEN_DIRECT_IMPORTS = (
    "framework.workflow",
    "framework.harness.workflow",
    "framework.scheduler",
    "framework.executor",
)


def _surface_files() -> list[Path]:
    return [
        path
        for root in SURFACE_ROOTS
        for path in root.rglob("*")
        if path.suffix in {".py", ".md"} and path.is_file()
    ]


def _client_surface_files() -> list[Path]:
    return [
        path
        for root in CLIENT_SURFACE_ROOTS
        for path in root.rglob("*")
        if path.suffix in {".ts", ".tsx"} and path.is_file()
    ]


def test_external_surfaces_have_no_retired_approval_or_state_patch_contract() -> None:
    violations = []
    for path in [*_surface_files(), *_client_surface_files()]:
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_PUBLIC_TOKENS:
            if token in text:
                violations.append(f"{path.relative_to(PROJECT_ROOT)}: {token}")
        if path in _client_surface_files():
            for token in ("workflow_id", "workflow_version", "workflow_ref"):
                if token in text:
                    violations.append(f"{path.relative_to(PROJECT_ROOT)}: {token}")
    assert violations == []


def test_api_cli_mcp_sdk_surface_modules_do_not_import_runtime_authority() -> None:
    violations: list[str] = []
    for path in _surface_files():
        if path.suffix != ".py":
            continue
        if path.name in {"__init__.py", "models.py", "transport.py"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            imported: str | None = None
            if isinstance(node, ast.Import):
                imported = node.names[0].name if node.names else None
            elif isinstance(node, ast.ImportFrom):
                imported = node.module
            if imported and imported.startswith(FORBIDDEN_DIRECT_IMPORTS):
                violations.append(f"{path.relative_to(PROJECT_ROOT)}: {imported}")
    assert violations == []
