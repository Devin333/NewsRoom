from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from storage.metrics.local import LocalStorageMetricsCollector


def storage_metrics_collector_from_env(
    *,
    artifact_root: str | Path = ".newsroom/runs",
    env: dict[str, str] | None = None,
) -> Any:
    values = env if env is not None else os.environ
    dsn = values.get("NEWS_DATABASE_DSN")
    if dsn:
        from storage.postgres import PostgresStorageMetricsCollector

        return PostgresStorageMetricsCollector(dsn)
    return LocalStorageMetricsCollector(artifact_root)
