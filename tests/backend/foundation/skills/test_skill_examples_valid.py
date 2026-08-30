from __future__ import annotations

from jsonschema import Draft202012Validator

from tests.backend.foundation.skills._helpers import load_json, skill_paths


def test_skill_examples_are_schema_valid_and_paired() -> None:
    for skill_path in skill_paths():
        input_schema = load_json(skill_path / "schemas" / "input.schema.json")
        output_schema = load_json(skill_path / "schemas" / "output.schema.json")
        input_validator = Draft202012Validator(input_schema)
        output_validator = Draft202012Validator(output_schema)

        input_cases = sorted(skill_path.glob("examples/case_*.input.json"))
        expected_cases = sorted(skill_path.glob("examples/case_*.expected.json"))
        input_ids = {path.name.removesuffix(".input.json") for path in input_cases}
        expected_ids = {path.name.removesuffix(".expected.json") for path in expected_cases}

        assert len(input_cases) >= 2, f"{skill_path.name} must include at least two input examples"
        assert input_ids == expected_ids, f"{skill_path.name} example case ids must be paired"

        for input_path in input_cases:
            input_validator.validate(load_json(input_path))

        for expected_path in expected_cases:
            output_validator.validate(load_json(expected_path))


def test_skill_examples_cover_prd_specific_expectations() -> None:
    source_case_001 = load_json(
        skill_paths()[0] / "examples" / "case_001.expected.json"
    )
    source_case_002 = load_json(
        skill_paths()[0] / "examples" / "case_002.expected.json"
    )
    assert source_case_001["source_tier"] == "primary"
    assert source_case_001["reliability_score"] > 0.9
    assert source_case_002["source_tier"] == "community"
    assert {"community_rumor", "low_evidence"}.issubset(set(source_case_002["risk_flags"]))

    entity_case_001 = load_json(
        skill_paths()[1] / "examples" / "case_001.expected.json"
    )
    entity_case_002 = load_json(
        skill_paths()[1] / "examples" / "case_002.expected.json"
    )
    assert {"company", "model", "event"}.issubset(
        {entity["type"] for entity in entity_case_001["entities"]}
    )
    assert {"repo", "framework", "metric"}.issubset(
        {entity["type"] for entity in entity_case_002["entities"]}
    )

    dedupe_case_001 = load_json(
        skill_paths()[2] / "examples" / "case_001.expected.json"
    )
    dedupe_case_002 = load_json(
        skill_paths()[2] / "examples" / "case_002.expected.json"
    )
    assert len(dedupe_case_001["event_groups"]) == 1
    assert dedupe_case_001["duplicate_pairs"][0]["same_event"] is True
    assert len(dedupe_case_002["event_groups"]) == 2
    assert dedupe_case_002["duplicate_pairs"][0]["same_event"] is False

    evidence_case_001 = load_json(
        skill_paths()[3] / "examples" / "case_001.expected.json"
    )
    evidence_case_002 = load_json(
        skill_paths()[3] / "examples" / "case_002.expected.json"
    )
    assert evidence_case_001["claim_results"][0]["status"] == "supported"
    assert evidence_case_002["claim_results"][0]["status"] == "unclear"
    assert evidence_case_002["claim_results"][0]["suggested_rewrite"]

    trend_case_001 = load_json(
        skill_paths()[4] / "examples" / "case_001.expected.json"
    )
    trend_case_002 = load_json(
        skill_paths()[4] / "examples" / "case_002.expected.json"
    )
    assert trend_case_001["event_analyses"][0]["trend_score"] > 0.75
    assert trend_case_001["event_analyses"][0]["watchlist_recommendation"] == "track"
    assert trend_case_002["event_analyses"][0]["trend_score"] < 0.5
    assert trend_case_002["event_analyses"][0]["watchlist_recommendation"] in {
        "monitor",
        "ignore",
    }

    report_case_001 = load_json(
        skill_paths()[5] / "examples" / "case_001.expected.json"
    )
    report_case_002 = load_json(
        skill_paths()[5] / "examples" / "case_002.expected.json"
    )
    assert report_case_001["markdown_report"].startswith("# AI Technical Daily")
    assert len(report_case_001["sections"]) == 2
    assert report_case_002["warnings"]
