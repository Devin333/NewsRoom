from __future__ import annotations

from pathlib import Path


_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def load_migration_sql() -> str:
    paths = sorted(_MIGRATIONS_DIR.glob("*.sql"))
    if not paths:
        raise FileNotFoundError(f"no SQL migrations found in {_MIGRATIONS_DIR}")
    sql_parts = [
        path.read_text(encoding="utf-8").strip()
        for path in paths
        if path.read_text(encoding="utf-8").strip()
    ]
    if not sql_parts:
        raise ValueError(f"SQL migrations in {_MIGRATIONS_DIR} are empty")
    return "\n\n".join(sql_parts)
