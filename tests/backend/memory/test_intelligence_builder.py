from backend.memory.intelligence_builder import IntelligenceMemoryBuilder


def test_builder_maps_evidence_bundle_to_bundle_layers() -> None:
    output = {
        "evidence_bundle": {
            "items": [
                {
                    "evidence_id": "ev-1",
                    "title": "Agent runtime update",
                    "summary": "Runtime added memory objects.",
                    "source_url": "https://example.com/a",
                    "source_item_id": "raw-1",
                    "confidence": 0.9,
                    "source_name": "Example",
                    "metadata": {"github_repo": "openai/newsroom"},
                }
            ]
        },
        "quality_result": {
            "decision": "pass",
            "reason": "quality ok",
            "quality_score": 0.91,
        },
    }

    bundle = IntelligenceMemoryBuilder().build_from_run_output(
        output,
        run_id="run-1",
        report_id="run-1:final",
        topic="AI",
    )

    assert bundle.counts()["evidence"] == 1
    assert bundle.evidence[0].source_urls == ["https://example.com/a"]
    assert bundle.claims[0].text == "Runtime added memory objects."
    assert bundle.claims[0].evidence_ids == ["ev-1"]
    assert {entity.entity_type for entity in bundle.entities} == {"topic", "source", "repository"}
    assert bundle.events[0].event_type == "general_news"
    assert bundle.events[0].evidence_ids == ["ev-1"]
    assert bundle.decisions[0].decision == "pass"
    assert bundle.decisions[0].output_scores["quality_score"] == 0.91


def test_builder_uses_first_non_empty_evidence_source_and_dedupes_claims() -> None:
    output = {
        "evidence_bundle": {"items": []},
        "evidence_items": [
            {"evidence_id": "ev-1", "title": "T1", "summary": "Same claim"},
            {"evidence_id": "ev-2", "title": "T2", "summary": " same   claim "},
        ],
        "final_report": {"evidence": [{"evidence_id": "ev-3", "summary": "ignored"}]},
    }

    bundle = IntelligenceMemoryBuilder().build_from_run_output(output, run_id="run-1", topic="AI")

    assert [item.evidence_id for item in bundle.evidence] == ["ev-1", "ev-2"]
    assert len(bundle.claims) == 1
    assert bundle.claims[0].evidence_ids == ["ev-1", "ev-2"]


def test_builder_can_build_from_final_report_quality() -> None:
    bundle = IntelligenceMemoryBuilder().build_from_run_output(
        {
            "final_report": {
                "metadata": {"topic": "AI policy"},
                "quality": {"status": "blocked", "scores": {"support": 0.2}},
            }
        },
        run_id="run-1",
    )

    assert bundle.topic == "AI policy"
    assert bundle.decisions[0].decision == "blocked"
    assert bundle.decisions[0].input_features == {"support": 0.2}
