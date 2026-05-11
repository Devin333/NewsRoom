from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from storage.artifacts.local_json import LocalJsonArtifactIndexStore


def artifact_index_store_from_env(
    *,
    artifact_root: str | Path = ".newsroom/runs",
    env: dict[str, str] | None = None,
) -> Any:
    values = env if env is not None else os.environ
    dsn = values.get("NEWS_DATABASE_DSN")
    if dsn:
        from storage.postgres import PostgresArtifactIndexStore

        return PostgresArtifactIndexStore(dsn)
    return LocalJsonArtifactIndexStore(Path(artifact_root) / "_records" / "artifact_index")
