from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from framework.artifacts.models import Artifact, ArtifactReference
from framework.artifacts.stores import ArtifactStore, LocalArtifactStore
from framework.governance import CompositeAndGate, GateCheckResult
from framework.shared.json import to_jsonable
from framework.workflow.runtime.manifest import (
    RUN_MANIFEST_SCHEMA_VERSION,
    append_manifest_artifact_index,
    manifest_hash,
    normalize_legacy_run_manifest,
    register_manifest_artifact,
    register_manifest_artifact_ref,
)


class ArtifactManager:
    def __init__(
        self,
        root: str | Path,
        *,
        store: ArtifactStore | None = None,
        gate_enabled: bool = True,
        max_write_bytes: int | None = None,
    ) -> None:
        self.root = Path(root)
        self.store = store or LocalArtifactStore(self.root)
        self.gate_enabled = gate_enabled
        self.max_write_bytes = max_write_bytes

    def publish(self, artifact: Artifact) -> ArtifactReference:
        return self.store.put(artifact)

    def resolve(self, ref: ArtifactReference) -> Artifact:
        artifact = self.store.get(ref.artifact_id)
        if artifact is None:
            raise FileNotFoundError(f"artifact not found: {ref.artifact_id}")
        return artifact

    def list(self, run_id: str | None = None) -> list[ArtifactReference]:
        return self.store.list(prefix=run_id)

    def delete(self, artifact_id: str) -> None:
        self.store.delete(artifact_id)

    def start_run(self, run_id: str) -> Path:
        run_dir = self.run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=False)
        return run_dir

    def run_dir(self, run_id: str) -> Path:
        return self.root / run_id

    def create_run_manifest(
        self,
        *,
        run_id: str,
        workflow_id: str | None = None,
        workflow_version: str | None = None,
        profile: str = "default",
        status: str = "created",
        started_at: str | None = None,
        run_type: str = "workflow",
    ) -> dict[str, Any]:
        manifest = normalize_legacy_run_manifest(
            {
                "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
                "run_type": run_type,
                "run_id": run_id,
                "workflow_id": workflow_id or "",
                "workflow_version": workflow_version or "",
                "profile": profile,
                "status": status,
                "started_at": started_at or "",
                "finished_at": None,
                "completed_at": None,
                "path": [],
                "steps": {},
                "artifacts": {"manifest": "manifest.json"},
            }
        )
        self.write_json(run_id, "manifest.json", manifest)
        return manifest

    def read_run_manifest(self, run_id: str) -> dict[str, Any]:
        path = self.run_dir(run_id) / "manifest.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        return normalize_legacy_run_manifest(payload)

    def update_run_manifest(self, run_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        manifest = self.read_run_manifest(run_id)
        manifest.update(dict(updates))
        manifest["manifest_hash"] = manifest_hash(manifest)
        self.write_json(run_id, "manifest.json", manifest)
        return manifest

    def append_manifest_artifact(
        self,
        run_id: str,
        *,
        artifact_key: str,
        relative_path: str,
        artifact_ref: ArtifactReference | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        manifest = self.read_run_manifest(run_id)
        register_manifest_artifact(manifest, artifact_key, relative_path)
        if artifact_ref is None:
            artifact_ref = ArtifactReference(
                artifact_id=artifact_key,
                run_id=run_id,
                kind=artifact_key,
                uri=relative_path,
            )
        register_manifest_artifact_ref(manifest, artifact_ref)
        payload = artifact_ref.to_dict() if isinstance(artifact_ref, ArtifactReference) else dict(artifact_ref)
        append_manifest_artifact_index(manifest, payload)
        manifest["manifest_hash"] = manifest_hash(manifest)
        self.write_json(run_id, "manifest.json", manifest)
        return manifest

    def finalize_run_manifest(self, run_id: str, updates: dict[str, Any] | None = None) -> dict[str, Any]:
        manifest = self.read_run_manifest(run_id)
        if updates:
            manifest.update(dict(updates))
        manifest["completed_at"] = manifest.get("completed_at") or manifest.get("finished_at")
        manifest["manifest_hash"] = manifest_hash(manifest)
        self.write_json(run_id, "manifest.json", manifest)
        return manifest

    def write_json(self, run_id: str, name: str, data: Any) -> Path:
        self._gate_write(run_id, name, json.dumps(to_jsonable(data), ensure_ascii=False).encode("utf-8"))
        target = self._target(run_id, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            json.dump(to_jsonable(data), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        return target

    def write_text(self, run_id: str, name: str, text: str) -> Path:
        self._gate_write(run_id, name, text.encode("utf-8"))
        target = self._target(run_id, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target

    def write_bytes(self, run_id: str, name: str, data: bytes) -> Path:
        self._gate_write(run_id, name, data)
        target = self._target(run_id, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def _target(self, run_id: str, name: str) -> Path:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"artifact name must be relative to the run directory: {name}")
        return self.run_dir(run_id) / relative

    def _gate_write(self, run_id: str, name: str, data: bytes) -> None:
        if not self.gate_enabled:
            return
        relative = Path(name)
        checks = [
            GateCheckResult(
                check_id="artifact.path",
                dimension="artifact",
                passed=not relative.is_absolute() and ".." not in relative.parts,
                reason=f"artifact path is not relative to run directory: {name}",
                metadata={"run_id": run_id, "name": name},
            )
        ]
        if self.max_write_bytes is not None:
            checks.append(
                GateCheckResult(
                    check_id="artifact.size",
                    dimension="resource",
                    passed=len(data) <= self.max_write_bytes,
                    reason=(
                        f"artifact write exceeds max_write_bytes: {len(data)} > {self.max_write_bytes}"
                    ),
                    metadata={"size_bytes": len(data), "max_write_bytes": self.max_write_bytes},
                )
            )
        if any(token in str(name).casefold() for token in ("secret", "token", "password")):
            checks.append(
                GateCheckResult(
                    check_id="artifact.sensitive_name",
                    dimension="safety",
                    passed=False,
                    severity="warning",
                    reason=f"artifact name looks sensitive: {name}",
                )
            )
        gate = CompositeAndGate(f"artifact:{run_id}:{name}:gate").evaluate(checks)
        if gate.decision == "block":
            raise ValueError(f"artifact gate blocked: {gate.reason}; gate_result={gate.to_dict()}")
