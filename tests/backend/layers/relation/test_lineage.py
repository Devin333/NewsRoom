from backend.layers.relation.lineage import evidence_bundle_lineage_extractor
from framework.shared.graph_identity import GraphRunIdentity


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
        graph_identity=GraphRunIdentity(
            run_id="run-1",
            graph_id="research.paper-analysis",
            graph_version="2",
            graph_ref="research.paper-analysis@2",
            graph_checksum="sha256:" + "a" * 64,
        ),
    )

    assert {ref.source_type for ref in refs} == {
        "evidence_bundle",
        "source_item",
        "source_url",
    }
    assert all(ref.run_id == "run-1" for ref in refs)
