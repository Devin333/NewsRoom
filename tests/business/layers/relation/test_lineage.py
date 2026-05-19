from business.layers.relation.lineage import evidence_bundle_lineage_extractor


def test_evidence_bundle_lineage_extractor_builds_business_lineage_refs() -> None:
    refs = evidence_bundle_lineage_extractor(
        output={
            "evidence_bundle": {
                "bundle_id": "bundle-1",
                "items": [
                    {
                        "evidence_id": "ev-1",
                        "source_url": "https://example.com/a",
                        "title": "Evidence",
                        "metadata": {"source_lineage": {"source_item_id": "raw-1"}},
                    }
                ],
            }
        },
        run_id="run-1",
        workflow_id="daily",
    )

    assert {ref.source_type for ref in refs} == {
        "evidence_bundle",
        "source_item",
        "source_url",
    }
    assert all(ref.run_id == "run-1" for ref in refs)
