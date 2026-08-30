from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from backend.research.rag.evaluation.golden_corpus_snapshot import (
    GoldenCorpusSnapshotError,
    load_golden_corpus_snapshot,
)

GOLDEN_SET = Path("data/eval/golden_set.json")
SNAPSHOT = Path("data/eval/golden_corpus_snapshot.json")


def test_repository_golden_corpus_snapshot_is_content_addressed() -> None:
    snapshot = load_golden_corpus_snapshot(
        SNAPSHOT,
        golden_set_path=GOLDEN_SET,
    )

    assert len(snapshot.source_documents) == 20
    assert len(snapshot.chunks) == 35
    assert {chunk.paper_id for chunk in snapshot.chunks} <= {
        item.paper_id for item in snapshot.source_documents
    }


def test_golden_corpus_snapshot_rejects_resealed_chunk_tampering(
    tmp_path: Path,
) -> None:
    payload = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    chunk = payload["chunks"][0]
    start = chunk["metadata"]["main_span"]["start"]
    chunk["content"] = chunk["content"][:start] + "tampered " + chunk["content"][start:]
    payload["snapshot_checksum"] = _snapshot_checksum(payload)
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(GoldenCorpusSnapshotError, match="content_hash mismatch"):
        load_golden_corpus_snapshot(tampered, golden_set_path=GOLDEN_SET)


def test_golden_corpus_snapshot_rejects_golden_set_byte_drift(
    tmp_path: Path,
) -> None:
    golden_set = tmp_path / "golden_set.json"
    golden_set.write_bytes(GOLDEN_SET.read_bytes() + b" ")

    with pytest.raises(GoldenCorpusSnapshotError, match="current golden set"):
        load_golden_corpus_snapshot(SNAPSHOT, golden_set_path=golden_set)


def _snapshot_checksum(payload: dict) -> str:
    checksum_payload = {
        key: payload[key] for key in sorted(payload) if key != "snapshot_checksum"
    }
    encoded = json.dumps(
        checksum_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
