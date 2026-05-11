from datetime import UTC, datetime

import pytest

from evidence import EvidenceBundle, EvidenceItem
from storage.lineage import LineageRef, LocalJsonLineageStore, lineage_refs_from_evidence_bundle


def _ref(source_type: str = "source_item", source_id: str = "raw-1") -> LineageRef:
    return LineageRef(
        run_id="run-1",
        source_type=source_type,
        source_id=source_id,
        target_type="evidence",
        target_id="ev-1",
        relation_type="source_to_evidence",
        created_at=datetime(2026, 5, 11, 1, 0, tzinfo=UTC),
        metadata={"workflow_id": "daily"},
    )


def test_lineage_ref_round_trips() -> None:
    ref = _ref()

    restored = LineageRef.from_dict(ref.to_dict())

    assert restored == ref
    assert restored.lineage_id == ref.lineage_id
    assert restored.to_dict()["created_at"] == "2026-05-11T01:00:00Z"


def test_local_json_lineage_store_records_and_queries(tmp_path) -> None:
    store = LocalJsonLineageStore(tmp_path)
    source_item = _ref("source_item", "raw-1")
    source_url = _ref("source_url", "https://example.com/item")

    path = store.record(source_item)
    store.record(source_url)

    assert path.exists()
    assert store.list_by_run("run-1") == [source_item, source_url]
    assert store.upstream("run-1", "evidence", "ev-1") == [source_item, source_url]
    assert store.downstream("run-1", "source_item", "raw-1") == [source_item]


def test_lineage_refs_from_evidence_bundle_extracts_source_lineage() -> None:
    bundle = EvidenceBundle(
        bundle_id="run-1",
        items=[
            EvidenceItem(
                evidence_id="ev-1",
                source_url="https://example.com/item",
                title="AI chips",
                summary="Chip summary",
                confidence=0.9,
                source_id="source",
                metadata={
                    "source_lineage": {
                        "source_item_id": "raw-1",
                        "normalized_item_id": "norm-1",
                        "ranked_item_id": "rank-1",
                    }
                },
            )
        ],
    )

    refs = lineage_refs_from_evidence_bundle(bundle, run_id="run-1", workflow_id="daily")

    source_pairs = {(ref.source_type, ref.source_id) for ref in refs}
    assert source_pairs == {
        ("source_url", "https://example.com/item"),
        ("source_item", "raw-1"),
        ("normalized_source_item", "norm-1"),
        ("ranked_source_item", "rank-1"),
    }
    assert all(ref.target_type == "evidence" and ref.target_id == "ev-1" for ref in refs)


def test_local_json_lineage_store_rejects_invalid_inputs(tmp_path) -> None:
    store = LocalJsonLineageStore(tmp_path)

    with pytest.raises(ValueError, match="invalid run_id"):
        store.list_by_run("../secret")

    with pytest.raises(ValueError, match="source_id is required"):
        store.record(_ref(source_id=""))
