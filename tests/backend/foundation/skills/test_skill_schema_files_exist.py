from __future__ import annotations

from jsonschema import Draft202012Validator

from tests.backend.foundation.skills._helpers import load_json, skill_paths


def test_skill_schema_files_are_valid_json_schema() -> None:
    for skill_path in skill_paths():
        for schema_name in ["input.schema.json", "output.schema.json"]:
            schema = load_json(skill_path / "schemas" / schema_name)

            assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
            assert schema["title"]
            assert schema["type"] == "object"
            Draft202012Validator.check_schema(schema)


def test_output_schemas_declare_required_fields() -> None:
    for skill_path in skill_paths():
        schema = load_json(skill_path / "schemas" / "output.schema.json")

        assert schema["required"], f"{skill_path.name} output schema must declare required fields"


def test_required_output_field_contracts_are_present() -> None:
    schemas = {
        skill_path.name: load_json(skill_path / "schemas" / "output.schema.json")
        for skill_path in skill_paths()
    }

    evidence_result = schemas["evidence-checking"]["properties"]["claim_results"]["items"]
    assert {
        "claim_id",
        "status",
        "supporting_source_ids",
        "contradicting_source_ids",
        "evidence_spans",
        "explanation",
        "suggested_rewrite",
    }.issubset(set(evidence_result["required"]))
    assert evidence_result["properties"]["status"]["enum"] == ["supported", "contradicted", "unclear"]
    assert {
        "supported_count",
        "contradicted_count",
        "unclear_count",
    }.issubset(set(schemas["evidence-checking"]["properties"]["summary"]["required"]))

    trend_result = schemas["trend-analysis"]["properties"]["event_analyses"]["items"]
    assert {
        "event_id",
        "trend_score",
        "momentum",
        "novelty",
        "impact_area",
        "why_it_matters",
        "watchlist_recommendation",
        "reasoning_summary",
    }.issubset(set(trend_result["required"]))
    assert trend_result["properties"]["momentum"]["enum"] == ["low", "medium", "high", "surging"]
    assert trend_result["properties"]["novelty"]["enum"] == [
        "incremental",
        "notable",
        "novel",
        "breakthrough_claim",
    ]
    assert trend_result["properties"]["watchlist_recommendation"]["enum"] == [
        "ignore",
        "monitor",
        "track",
        "escalate",
    ]

    report = schemas["report-writing"]
    assert {
        "markdown_report",
        "summary",
        "sections",
        "citations",
        "warnings",
    }.issubset(set(report["required"]))
    assert {"title", "content", "item_ids"}.issubset(
        set(report["properties"]["sections"]["items"]["required"])
    )
    assert {"item_id", "url", "source_name"}.issubset(
        set(report["properties"]["citations"]["items"]["required"])
    )
