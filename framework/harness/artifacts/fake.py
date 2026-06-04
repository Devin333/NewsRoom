from __future__ import annotations

import hashlib

from framework.harness.artifacts.ports import ArtifactRef, ArtifactWriteRequest
from framework.shared.json import stable_json_dumps


class FakeArtifactPort:
    def __init__(self) -> None:
        self.storage: dict[str, dict] = {}
        self.refs: dict[str, ArtifactRef] = {}

    def write_artifact(self, request: ArtifactWriteRequest) -> ArtifactRef:
        checksum = hashlib.sha256(stable_json_dumps(request.to_dict()).encode()).hexdigest()
        ref = f"artifact://fake/{len(self.storage) + 1}"
        artifact_ref = ArtifactRef(
            ref=ref,
            artifact_type=request.artifact_type,
            checksum=f"sha256:{checksum}",
            media_type=request.media_type,
            metadata=request.metadata,
        )
        self.storage[ref] = request.to_dict()
        self.refs[ref] = artifact_ref
        return artifact_ref

    def read_artifact(self, ref: str) -> dict:
        return dict(self.storage[ref])


__all__ = ["FakeArtifactPort"]
