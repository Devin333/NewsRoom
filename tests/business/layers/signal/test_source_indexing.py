import json

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
