from dataclasses import replace
from datetime import UTC, datetime

import pytest

from business.layers.relation.evidence import EvidenceBundle, EvidenceItem
from framework.agent.artifacts import ArtifactPathError
from infrastructure.storage.lineage import LineageRef, LocalJsonLineageStore, lineage_refs_from_evidence_bundle


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


def test_local_json_lineage_store_preserves_logical_source_and_target_ids(tmp_path) -> None:
    store = LocalJsonLineageStore(tmp_path)
    ref = replace(
        _ref(),
        source_id="source:logical-id",
        target_id="target:logical-id",
        lineage_id=None,
    )

    store.record(ref)

    assert store.list_by_run("run-1") == [ref]


@pytest.mark.parametrize("run_id", ["../secret", "run:stream", "CON", " run-1"])
def test_local_json_lineage_store_rejects_unsafe_run_id_without_side_effect(
    tmp_path,
    run_id: str,
) -> None:
    store = LocalJsonLineageStore(tmp_path)

    with pytest.raises(ArtifactPathError):
        store.record(replace(_ref(), run_id=run_id, lineage_id=None))

    assert list(tmp_path.iterdir()) == []


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
        metadata={"report_id": "run-1:final"},
    )
    bundle_payload = bundle.to_dict()
    bundle_payload["candidate_claims"] = [
        {
            "claim_id": "claim-1",
            "text": "AI chips remain central.",
            "source_evidence_ids": ["ev-1"],
        }
    ]
    bundle_payload["report_id"] = "run-1:final"

    refs = lineage_refs_from_evidence_bundle(bundle_payload, run_id="run-1", workflow_id="daily")

    source_pairs = {(ref.source_type, ref.source_id) for ref in refs}
    assert source_pairs >= {
        ("source_url", "https://example.com/item"),
        ("source_item", "raw-1"),
        ("normalized_source_item", "norm-1"),
        ("ranked_source_item", "rank-1"),
        ("evidence_bundle", "run-1"),
        ("evidence", "ev-1"),
        ("claim", "claim-1"),
    }
    assert any(ref.target_type == "claim" and ref.target_id == "claim-1" for ref in refs)
    assert any(ref.target_type == "report" and ref.target_id == "run-1:final" for ref in refs)




def test_local_json_lineage_store_retrieval_contract_is_stable(tmp_path) -> None:
    store = LocalJsonLineageStore(tmp_path)
    upstream_ref = _ref("source_item", "raw-1")
    downstream_ref = LineageRef(
        run_id="run-1",
        source_type="claim",
        source_id="claim-1",
        target_type="report",
        target_id="run-1:final",
        relation_type="claim_to_report",
        created_at=datetime(2026, 5, 11, 1, 0, tzinfo=UTC),
        metadata={"workflow_id": "daily"},
    )
    store.record_many([upstream_ref, downstream_ref])

    listed = store.list_by_run("run-1")
    upstream = store.upstream("run-1", "evidence", "ev-1")
    downstream = store.downstream("run-1", "claim", "claim-1")

    assert [ref.lineage_id for ref in listed] == [upstream_ref.lineage_id, downstream_ref.lineage_id]
    assert upstream == [upstream_ref]
    assert downstream == [downstream_ref]
    store = LocalJsonLineageStore(tmp_path)

    with pytest.raises(ValueError, match="invalid run_id"):
        store.list_by_run("../secret")

    with pytest.raises(ValueError, match="source_id is required"):
        store.record(_ref(source_id=""))
