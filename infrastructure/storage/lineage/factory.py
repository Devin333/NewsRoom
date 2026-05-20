from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from infrastructure.storage.lineage.local_json import LocalJsonLineageStore


def lineage_store_from_env(
    *,
    artifact_root: str | Path = ".newsroom/runs",
    env: dict[str, str] | None = None,
) -> Any:
    values = env if env is not None else os.environ
    dsn = values.get("NEWS_DATABASE_DSN")
    if dsn:
        from infrastructure.storage.postgres import PostgresLineageStore

        return PostgresLineageStore(dsn)
    return LocalJsonLineageStore(Path(artifact_root) / "_records" / "lineage")
