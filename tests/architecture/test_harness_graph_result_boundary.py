from __future__ import annotations

from tests.architecture._helpers import PROJECT_ROOT, imported_modules, matches_prefix


RESULT_BOUNDARY_MODULES = (
    PROJECT_ROOT / "framework" / "harness" / "graph" / "result_lineage.py",
    PROJECT_ROOT / "framework" / "harness" / "runtime" / "graph_result_projection.py",
    PROJECT_ROOT / "framework" / "harness" / "runtime" / "graph_result_runtime.py",
)
CONTROL_PLANE_MODULE = (
    PROJECT_ROOT / "framework" / "harness" / "control_plane" / "harness.py"
)
FORBIDDEN_IMPORTS = (
    "business",
    "interfaces",
    "infrastructure",
    "storage",
    "framework.harness.workers",
    "framework.tools",
    "framework.tool",
    "framework.mcp",
    "psycopg",
    "redis",
    "sqlalchemy",
)


def test_graph_result_projection_boundary_has_no_business_worker_or_storage_imports() -> None:
    violations = [
        f"{path.relative_to(PROJECT_ROOT).as_posix()}: {module}"
        for path in RESULT_BOUNDARY_MODULES
        for module in imported_modules(path)
        if matches_prefix(module, FORBIDDEN_IMPORTS)
    ]

    assert violations == []


def test_graph_lineage_does_not_import_runtime_envelope() -> None:
    lineage = RESULT_BOUNDARY_MODULES[0]

    assert all(
        not matches_prefix(module, ("framework.harness.runtime",))
        for module in imported_modules(lineage)
    )


def test_graph_result_lineage_has_no_control_plane_path_shim() -> None:
    assert RESULT_BOUNDARY_MODULES[0].is_file()
    assert not (
        PROJECT_ROOT
        / "framework"
        / "harness"
        / "control_plane"
        / "graph_result_lineage.py"
    ).exists()


def test_graph_result_committer_boundary_has_no_storage_or_business_imports() -> None:
    forbidden = (
        "business",
        "interfaces",
        "infrastructure",
        "storage",
        "framework.harness.artifacts",
        "framework.harness.runtime",
        "psycopg",
        "redis",
        "sqlalchemy",
        "sqlite3",
    )

    assert all(
        not matches_prefix(module, forbidden)
        for module in imported_modules(CONTROL_PLANE_MODULE)
    )
