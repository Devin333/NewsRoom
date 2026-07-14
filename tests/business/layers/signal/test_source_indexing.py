import json

import pytest

from business.layers.signal.artifact_refs import SignalArtifactRef
from business.layers.signal.indexing import source_artifact_ref_extractor


def test_source_artifact_ref_extractor_reads_source_artifact_index(tmp_path) -> None:
    run_dir = tmp_path / "run-1"
    artifact_path = run_dir / "sources" / "items" / "feed" / "item-1.json"
    index_path = run_dir / "source_artifacts" / "index.json"
    artifact_path.parent.mkdir(parents=True)
    index_path.parent.mkdir(parents=True)
    artifact_path.write_text('{"title": "Item"}', encoding="utf-8")
    ref = SignalArtifactRef(
        artifact_id="source-item-feed-item-1",
        run_id="run-1",
        artifact_type="source_item",
        path="sources/items/feed/item-1.json",
        content_type="application/json",
        size_bytes=17,
        checksum="abc",
        redacted=True,
        metadata={"source_id": "feed"},
    )
    index_path.write_text(
        json.dumps({"entries": [{"artifact_ref": ref.to_dict()}]}),
        encoding="utf-8",
    )

    refs = source_artifact_ref_extractor(
        run_dir=run_dir,
        manifest={"artifacts": {"source_artifacts": "source_artifacts/index.json"}},
        output={},
    )

    assert refs == [ref]


def test_source_artifact_ref_extractor_rejects_linked_index_outside_run(tmp_path) -> None:
    run_dir = tmp_path / "run-1"
    artifact_path = run_dir / "sources" / "item.json"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text('{}', encoding="utf-8")
    ref = _artifact_ref(path="sources/item.json")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "index.json").write_text(
        json.dumps({"entries": [{"artifact_ref": ref.to_dict()}]}),
        encoding="utf-8",
    )
    link = run_dir / "linked"
    _symlink_directory(link, outside)

    refs = source_artifact_ref_extractor(
        run_dir=run_dir,
        manifest={"artifacts": {"source_artifacts": "linked/index.json"}},
        output={},
    )

    assert refs == []


def test_source_artifact_ref_extractor_rejects_linked_ref_outside_run(tmp_path) -> None:
    run_dir = tmp_path / "run-1"
    index_path = run_dir / "source_artifacts" / "index.json"
    index_path.parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "item.json").write_text('{}', encoding="utf-8")
    link = run_dir / "linked"
    _symlink_directory(link, outside)
    ref = _artifact_ref(path="linked/item.json")
    index_path.write_text(
        json.dumps({"entries": [{"artifact_ref": ref.to_dict()}]}),
        encoding="utf-8",
    )

    refs = source_artifact_ref_extractor(
        run_dir=run_dir,
        manifest={"artifacts": {"source_artifacts": "source_artifacts/index.json"}},
        output={},
    )

    assert refs == []


def _artifact_ref(*, path: str) -> SignalArtifactRef:
    return SignalArtifactRef(
        artifact_id="source-item-feed-item-1",
        run_id="run-1",
        artifact_type="source_item",
        path=path,
        content_type="application/json",
        size_bytes=2,
        checksum="abc",
        redacted=True,
        metadata={"source_id": "feed"},
    )


def _symlink_directory(link, target) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")
