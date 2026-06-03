from __future__ import annotations

from business.layers.output.report_quality_projection import (
    normalize_quality_result_records,
    project_quality_result_record_payload,
    project_report_quality_payload,
)


def test_project_report_quality_payload_prefers_report_quality_trace() -> None:
    quality = project_report_quality_payload(
        {"quality_trace": {"decision": "blocked"}},
        quality_records=[
            {
                "decision": "pass",
                "passed": True,
                "payload": {"quality_result": {"decision": "pass"}},
            }
        ],
    )

    assert quality == {"decision": "blocked"}


def test_project_report_quality_payload_falls_back_to_quality_record_payload() -> None:
    quality = project_report_quality_payload(
        {"title": "Report"},
        quality_records=[
            {
                "decision": "blocked",
                "passed": False,
                "quality_score": 0.2,
                "payload": {
                    "quality_result": {
                        "decision": "human_review",
                        "route": "human_review",
                    }
                },
            }
        ],
    )

    assert quality == {
        "decision": "human_review",
        "route": "human_review",
        "passed": False,
        "quality_score": 0.2,
    }


def test_project_quality_result_record_payload_uses_top_level_scalars() -> None:
    quality = project_quality_result_record_payload(
        {
            "decision": "pass",
            "passed": True,
            "quality_score": 0.9,
            "citation_coverage_score": 0.8,
            "payload": {},
        }
    )

    assert quality == {
        "decision": "pass",
        "passed": True,
        "quality_score": 0.9,
        "citation_coverage_score": 0.8,
    }


def test_normalize_quality_result_records_accepts_record_objects() -> None:
    records = normalize_quality_result_records([_Record({"quality_result_id": "quality-1"})])

    assert records == [{"quality_result_id": "quality-1"}]


class _Record:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def to_dict(self) -> dict:
        return dict(self.payload)
