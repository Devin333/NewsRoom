from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from business.layers.signal.artifact_refs import SignalArtifactRef


def source_artifact_ref_extractor(
    *,
    run_dir: Path,
    manifest: dict[str, Any],
    output: dict[str, Any],
) -> list[SignalArtifactRef]:
    artifact_paths = manifest.get("artifacts") or {}
    source_index_path = artifact_paths.get("source_artifacts")
    if not isinstance(source_index_path, str):
        return []
    try:
        index_path = _artifact_path(run_dir, source_index_path)
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return []

    refs: list[SignalArtifactRef] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        ref_payload = entry.get("artifact_ref")
        if not isinstance(ref_payload, dict):
            continue
        try:
            ref = SignalArtifactRef.from_dict(ref_payload)
            _artifact_path(run_dir, ref.path)
        except (KeyError, TypeError, ValueError, OSError):
            continue
        refs.append(ref)
    return refs


def _artifact_path(run_dir: Path, relative_path: str) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"invalid artifact path: {relative_path}")
    path = run_dir / relative
    if not path.exists():
        raise FileNotFoundError(f"artifact file not found: {relative_path}")
    return path
