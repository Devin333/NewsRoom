from __future__ import annotations

import json
from pathlib import Path

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
        return StorageMetrics(
            runs_count=len(manifests),
            reports_count=sum(1 for manifest in manifests if _has_report_artifact(manifest)),
            artifacts_count=len(artifact_refs),
            source_items_count=self._json_record_count("source_items"),
            evidence_items_count=self._json_record_count("evidence_items"),
            claims_count=self._json_record_count("claims"),
            quality_results_count=self._json_record_count("quality_results"),
            artifact_bytes_total=sum(ref.size_bytes or 0 for ref in artifact_refs),
            events_count=self._jsonl_line_count(self.artifact_root / "_records" / "events"),
            lineage_refs_count=self._jsonl_line_count(self.artifact_root / "_records" / "lineage"),
            metadata={
                "artifact_root": str(self.artifact_root),
                "source": "local_json",
            },
        )

    def _manifest_payloads(self) -> list[dict]:
        manifests = []
        for path in self.artifact_root.glob("*/manifest.json"):
            if path.parts and "_records" in path.parts:
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                manifests.append(payload)
        return manifests

    def _artifact_refs(self) -> list[ArtifactRef]:
        refs = []
        index_root = self.artifact_root / "_records" / "artifact_index"
        for path in index_root.glob("*/*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                refs.append(ArtifactRef.from_dict(payload))
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
        return refs

    def _jsonl_line_count(self, root: Path) -> int:
        count = 0
        for path in root.glob("*.jsonl"):
            try:
                with path.open("r", encoding="utf-8") as handle:
                    count += sum(1 for line in handle if line.strip())
            except OSError:
                continue
        return count

    def _json_record_count(self, name: str) -> int:
        root = self.artifact_root / "_records" / name
        if not root.exists():
            return 0
        return sum(1 for path in root.rglob("*.json") if path.is_file())


def _has_report_artifact(manifest: dict) -> bool:
    artifacts = manifest.get("artifacts") or {}
    if not isinstance(artifacts, dict):
        return False
    return any(
        _REPORT_TYPE_POLICY.retention_days_for(str(artifact_type)) == _REPORT_RETENTION_SENTINEL_DAYS
        for artifact_type in artifacts
    )
