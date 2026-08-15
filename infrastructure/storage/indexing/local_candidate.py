from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from framework.agent.artifacts.stores.errors import ArtifactStoreMetadataError
from framework.agent.artifacts.stores.fs_safety import (
    is_link_or_reparse_point,
    reject_link_chain,
    verified_atomic_write,
    verified_exclusive_file_lock,
)
from framework.shared.json import stable_json_dumps
from infrastructure.storage.indexing.contracts import (
    GraphIndexCandidateStageReceipt,
    GraphIndexStageStatus,
    GraphStorageIndexCandidate,
    GraphStorageIndexError,
    GraphStorageIndexErrorCode,
)


DEFAULT_MAX_GRAPH_INDEX_CANDIDATE_BYTES = 256 * 1024 * 1024


class LocalGraphIndexCandidateStore:
    """Durable candidate-only store with no production pointer authority."""

    def __init__(
        self,
        root: str | Path,
        *,
        max_candidate_bytes: int = DEFAULT_MAX_GRAPH_INDEX_CANDIDATE_BYTES,
    ) -> None:
        self.root = Path(root)
        if (
            isinstance(max_candidate_bytes, bool)
            or not isinstance(max_candidate_bytes, int)
            or max_candidate_bytes < 1
        ):
            raise ValueError("max_candidate_bytes must be a positive integer")
        self.max_candidate_bytes = max_candidate_bytes

    def stage_candidate(
        self,
        candidate: GraphStorageIndexCandidate,
    ) -> GraphIndexCandidateStageReceipt:
        if not isinstance(candidate, GraphStorageIndexCandidate):
            raise TypeError("candidate must be GraphStorageIndexCandidate")
        candidate.verify_integrity()
        target = self._candidate_path(candidate.candidate_ref)
        lock_path = target.with_suffix(".lock")
        content = (
            stable_json_dumps(candidate.to_dict()).encode("utf-8") + b"\n"
        )
        if len(content) > self.max_candidate_bytes:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.REQUEST_INVALID,
                "Graph index candidate exceeds the configured storage bound",
                field="candidate",
            )
        identity = f"Graph index candidate {candidate.candidate_ref}"
        try:
            with verified_exclusive_file_lock(
                lock_path,
                root=self.root,
                identity=identity,
            ):
                try:
                    existing = self.read_candidate(candidate.candidate_ref)
                except GraphStorageIndexError as exc:
                    if exc.code is not GraphStorageIndexErrorCode.CANDIDATE_NOT_FOUND:
                        raise
                else:
                    if existing.candidate_checksum != candidate.candidate_checksum:
                        raise GraphStorageIndexError(
                            GraphStorageIndexErrorCode.CANDIDATE_CONFLICT,
                            "Graph index candidate identity already has another body",
                            field="candidate_checksum",
                        )
                    return self._receipt(
                        candidate,
                        status=GraphIndexStageStatus.IDEMPOTENT,
                    )
                verified_atomic_write(
                    target,
                    content,
                    root=self.root,
                    identity=identity,
                )
        except ArtifactStoreMetadataError as exc:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.CANDIDATE_CORRUPT,
                "Graph index candidate storage boundary rejected the target",
                field="candidate_path",
            ) from exc
        return self._receipt(candidate, status=GraphIndexStageStatus.STAGED)

    def read_candidate(self, candidate_ref: str) -> GraphStorageIndexCandidate:
        target = self._candidate_path(candidate_ref)
        identity = f"Graph index candidate {candidate_ref}"
        canonical_root = self.root.resolve(strict=False)
        try:
            reject_link_chain(
                target,
                root=canonical_root,
                identity=identity,
                role="Graph index candidate",
            )
            info = os.lstat(target)
        except FileNotFoundError as exc:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.CANDIDATE_NOT_FOUND,
                "Graph index candidate was not found",
                field="candidate_ref",
            ) from exc
        except ArtifactStoreMetadataError as exc:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.CANDIDATE_CORRUPT,
                "Graph index candidate path is unsafe",
                field="candidate_path",
            ) from exc
        if not stat.S_ISREG(info.st_mode) or is_link_or_reparse_point(info):
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.CANDIDATE_CORRUPT,
                "Graph index candidate is not a regular file",
                field="candidate_path",
            )
        if info.st_size > self.max_candidate_bytes:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.CANDIDATE_CORRUPT,
                "Graph index candidate exceeds the read bound",
                field="candidate_path",
            )
        try:
            payload = json.loads(
                target.read_text(encoding="utf-8"),
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
            )
        except (OSError, UnicodeError, TypeError, ValueError) as exc:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.CANDIDATE_CORRUPT,
                "Graph index candidate content is invalid",
                field="candidate",
            ) from exc
        try:
            candidate = GraphStorageIndexCandidate.from_dict(payload)
        except (GraphStorageIndexError, TypeError, ValueError) as exc:
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.CANDIDATE_CORRUPT,
                "Graph index candidate contract is invalid",
                field="candidate",
            ) from exc
        if candidate.candidate_ref != _candidate_ref(candidate_ref):
            raise GraphStorageIndexError(
                GraphStorageIndexErrorCode.CANDIDATE_SCOPE_MISMATCH,
                "Graph index candidate read-back changed the requested identity",
                field="candidate_ref",
            )
        return candidate

    def _candidate_path(self, candidate_ref: str) -> Path:
        normalized = _candidate_ref(candidate_ref)
        digest = normalized.removeprefix("sha256:")
        return self.root / f"candidate-{digest}.json"

    @staticmethod
    def _receipt(
        candidate: GraphStorageIndexCandidate,
        *,
        status: GraphIndexStageStatus,
    ) -> GraphIndexCandidateStageReceipt:
        digest = candidate.candidate_ref.removeprefix("sha256:")
        return GraphIndexCandidateStageReceipt(
            candidate_ref=candidate.candidate_ref,
            candidate_checksum=candidate.candidate_checksum,
            storage_ref=f"graph-index-candidate://{digest}",
            status=status,
        )


def _candidate_ref(value: Any) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise GraphStorageIndexError(
            GraphStorageIndexErrorCode.REQUEST_INVALID,
            "candidate_ref must be a sha256 checksum",
            field="candidate_ref",
        )
    digest = value.removeprefix("sha256:")
    if (
        len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise GraphStorageIndexError(
            GraphStorageIndexErrorCode.REQUEST_INVALID,
            "candidate_ref must be a sha256 checksum",
            field="candidate_ref",
        )
    return value


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"invalid JSON constant: {value}")


__all__ = [
    "DEFAULT_MAX_GRAPH_INDEX_CANDIDATE_BYTES",
    "LocalGraphIndexCandidateStore",
]
