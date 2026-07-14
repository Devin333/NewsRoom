from __future__ import annotations

import json
from pathlib import Path

from framework.artifacts.paths import resolve_artifact_descendant
from infrastructure.storage.artifacts import ArtifactRef
from infrastructure.storage.lifecycle.retention import RetentionPolicy
from infrastructure.storage.metrics.models import StorageMetrics


_REPORT_RETENTION_SENTINEL_DAYS = 123456789
_REPORT_TYPE_POLICY = RetentionPolicy(report_retention_days=_REPORT_RETENTION_SENTINEL_DAYS)


class LocalStorageMetricsCollector:
    def __init__(self, artifact_root: str | Path = ".newsroom/runs") -> None:
        self.artifact_root = Path(artifact_root)

    def collect(self) -> StorageMetrics:
        manifests = self._manifest_payloads()
        artifact_refs = self._artifact_refs()
        events_root = resolve_artifact_descendant(
            self.artifact_root,
            "_records/events",
            field="storage events root",
        )
        lineage_root = resolve_artifact_descendant(
            self.artifact_root,
            "_records/lineage",
            field="storage lineage root",
        )
        return StorageMetrics(
            runs_count=len(manifests),
            reports_count=sum(1 for manifest in manifests if _has_report_artifact(manifest)),
            artifacts_count=len(artifact_refs),
            source_items_count=self._json_record_count("source_items"),
            evidence_items_count=self._json_record_count("evidence_items"),
            claims_count=self._json_record_count("claims"),
            quality_results_count=self._json_record_count("quality_results"),
            artifact_bytes_total=sum(ref.size_bytes or 0 for ref in artifact_refs),
            events_count=self._jsonl_line_count(events_root),
            lineage_refs_count=self._jsonl_line_count(lineage_root),
            metadata={
                "artifact_root": str(self.artifact_root),
                "source": "local_json",
            },
        )

    def _manifest_payloads(self) -> list[dict]:
        manifests = []
        artifact_root = self.artifact_root.resolve(strict=False)
        for candidate in artifact_root.glob("*/manifest.json"):
            if candidate.parts and "_records" in candidate.parts:
                continue
            path = resolve_artifact_descendant(
                artifact_root,
                candidate.relative_to(artifact_root).as_posix(),
                field="storage manifest path",
            )
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                manifests.append(payload)
        return manifests

    def _artifact_refs(self) -> list[ArtifactRef]:
        refs = []
        index_root = resolve_artifact_descendant(
            self.artifact_root,
            "_records/artifact_index",
            field="artifact index root",
        )
        for candidate in index_root.glob("*/*.json"):
            path = resolve_artifact_descendant(
                index_root,
                candidate.relative_to(index_root).as_posix(),
                field="artifact index record",
            )
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                refs.append(ArtifactRef.from_dict(payload))
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
        return refs

    def _jsonl_line_count(self, root: Path) -> int:
        count = 0
        for candidate in root.glob("*.jsonl"):
            path = resolve_artifact_descendant(
                root,
                candidate.name,
                field="storage record path",
            )
            try:
                with path.open("r", encoding="utf-8") as handle:
                    count += sum(1 for line in handle if line.strip())
            except OSError:
                continue
        return count

    def _json_record_count(self, name: str) -> int:
        root = resolve_artifact_descendant(
            self.artifact_root,
            f"_records/{name}",
            field="storage record root",
        )
        if not root.exists():
            return 0
        count = 0
        for candidate in root.rglob("*.json"):
            path = resolve_artifact_descendant(
                root,
                candidate.relative_to(root).as_posix(),
                field="storage record path",
            )
            if path.is_file():
                count += 1
        return count


def _has_report_artifact(manifest: dict) -> bool:
    artifacts = manifest.get("artifacts") or {}
    if not isinstance(artifacts, dict):
        return False
    return any(
        _REPORT_TYPE_POLICY.retention_days_for(str(artifact_type)) == _REPORT_RETENTION_SENTINEL_DAYS
        for artifact_type in artifacts
    )
