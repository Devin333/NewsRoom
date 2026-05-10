from __future__ import annotations

from pathlib import Path


def load_migration_sql() -> str:
    migrations_dir = Path(__file__).parent / "migrations"
    return "\n\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(migrations_dir.glob("*.sql"))
    )
