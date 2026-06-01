import json
from datetime import datetime, timezone

from framework.agent.subagents import PaperReaderArtifactReviewSubAgent, SubAgentTask


def test_paper_reader_artifact_reviewer_records_issue_memory_and_matches_repeats(tmp_path) -> None:
    memory_path = tmp_path / "paper-reader-artifact-review-memory.json"
    reviewer = PaperReaderArtifactReviewSubAgent(clock=lambda: datetime(2026, 6, 1, tzinfo=timezone.utc))

    first = reviewer.review(
        document=_document("paper-1", text="rll & Website &", latex=r"\begin{tabular}{rll}"),
        manifest=_manifest("paper-1"),
        paper_dir=tmp_path,
        memory_path=memory_path,
    )
    second = reviewer.review(
        document=_document("paper-2", text="rll & Website &", latex=r"\begin{tabular}{rll}"),
        manifest=_manifest("paper-2"),
        paper_dir=tmp_path,
        memory_path=memory_path,
    )

    assert first["passed"] is False
    assert any(error["code"] == "table_alignment_symbols_visible" for error in first["errors"])
    assert first["memory"]["saved"] is True
    assert second["passed"] is False
    assert second["memory"]["matchCount"] >= 1
    repeated = next(error for error in second["errors"] if error["code"] == "table_alignment_symbols_visible")
    assert repeated["memoryMatch"]["seenCount"] == 1
    assert repeated["memoryMatch"]["lastLocator"]["paperId"] == "paper-1"
    assert repeated["memoryMatch"]["recentLocators"][0]["paperId"] == "paper-1"

    payload = json.loads(memory_path.read_text(encoding="utf-8"))
    assert payload["schemaVersion"] == "paper_reader_artifact_review_memory_v1"
    stored = next(iter(payload["issues"].values()))
    assert stored["seenCount"] == 2
    assert stored["lastLocator"]["paperId"] == "paper-2"
    assert len(stored["occurrences"]) == 2


def test_paper_reader_artifact_reviewer_memory_records_each_raw_occurrence(tmp_path) -> None:
    memory_path = tmp_path / "paper-reader-artifact-review-memory.json"
    reviewer = PaperReaderArtifactReviewSubAgent(clock=lambda: datetime(2026, 6, 1, tzinfo=timezone.utc))

    result = reviewer.review(
        document=_document("paper-assets", text="Clean paragraph"),
        manifest=_manifest(
            "paper-assets",
            assets=[
                _figure_asset("figure-a", label=""),
                _figure_asset("figure-b", label=""),
            ],
        ),
        paper_dir=tmp_path,
        memory_path=memory_path,
    )

    assert sum(1 for error in result["errors"] if error["code"] == "asset_label_missing") == 1

    payload = json.loads(memory_path.read_text(encoding="utf-8"))
    remembered = [
        issue
        for issue in payload["issues"].values()
        if issue["code"] == "asset_label_missing"
    ][0]
    assert remembered["seenCount"] == 2
    assert [item["locator"]["assetId"] for item in remembered["occurrences"]] == ["figure-a", "figure-b"]


def test_paper_reader_artifact_reviewer_detects_equation_table_and_symbol_gates(tmp_path) -> None:
    reviewer = PaperReaderArtifactReviewSubAgent(clock=lambda: datetime(2026, 6, 1, tzinfo=timezone.utc))
    document = _document(
        "paper-gates",
        text="Good paragraph",
        blocks=[
            {
                "id": "equation-1",
                "paperId": "paper-gates",
                "type": "equation",
                "text": r"\begin{small} x = y \end{small}",
                "source": {"pageNumber": 1, "bbox": {"x0": 0, "y0": 0, "x1": 10, "y1": 10}},
                "metadata": {},
            },
            {
                "id": "table-1",
                "paperId": "paper-gates",
                "type": "table",
                "text": "Table 1",
                "assetId": "table-asset",
                "label": "Table 1",
                "caption": "Table 1",
                "source": {"pageNumber": 1, "bbox": {"x0": 0, "y0": 0, "x1": 10, "y1": 10}},
                "metadata": {"tableModel": {"rows": [{"cells": [{"text": ""}]}]}},
            },
            {
                "id": "paragraph-1",
                "paperId": "paper-gates",
                "type": "paragraph",
                "text": "AT&amp;T should not leak as escaped HTML.",
                "source": {"pageNumber": 1, "bbox": {"x0": 0, "y0": 0, "x1": 10, "y1": 10}},
                "metadata": {},
            },
        ],
    )
    manifest = _manifest(
        "paper-gates",
        assets=[
            {
                "assetId": "table-asset",
                "paperId": "paper-gates",
                "kind": "table",
                "fileName": "assets/table.html",
                "mimeType": "text/html; charset=utf-8",
                "width": 320,
                "height": 120,
                "checksum": "checksum",
                "pageNumber": 1,
                "label": "Table 1",
                "caption": "Table 1",
                "source": {"pageNumber": 1, "bbox": {"x0": 0, "y0": 0, "x1": 10, "y1": 10}},
                "metadata": {"tableModel": {"rows": [{"cells": [{"text": ""}]}]}, "tableHtml": "<table></table>"},
            }
        ],
    )

    result = reviewer.review(document=document, manifest=manifest, paper_dir=tmp_path, memory_path=tmp_path / "memory.json")

    assert result["passed"] is False
    codes = {issue["code"] for issue in result["errors"]}
    assert "equation_contains_formatting_environment" in codes
    assert "table_model_has_no_readable_cells" in codes
    assert "html_entity_visible" in codes
    assert {gate["name"]: gate["passed"] for gate in result["gates"]} == {
        "image": True,
        "table": False,
        "equation": False,
        "symbol": False,
    }


def test_paper_reader_artifact_reviewer_execute_returns_subagent_result(tmp_path) -> None:
    reviewer = PaperReaderArtifactReviewSubAgent(clock=lambda: datetime(2026, 6, 1, tzinfo=timezone.utc))

    result = reviewer.execute(
        SubAgentTask(
            parent_agent_id="compiler",
            child_agent_id="paper-reader-artifact-reviewer-v1",
            task="review compiled paper",
            inputs={
                "document": _document("paper-1", text="Clean paragraph"),
                "manifest": _manifest("paper-1"),
                "paper_dir": str(tmp_path),
                "memory_path": str(tmp_path / "memory.json"),
            },
        )
    )

    assert result.success is True
    assert result.output["passed"] is True
    assert result.output["memory"]["saved"] is True


def _document(paper_id: str, *, text: str, latex: str = "", blocks=None):
    return {
        "paperId": paper_id,
        "schemaVersion": "paper_document_v1",
        "status": "needs_review",
        "title": "Paper",
        "compiledAt": "2026-06-01T00:00:00Z",
        "sourceHash": "hash",
        "blocks": blocks
        if blocks is not None
        else [
            {
                "id": "paragraph-1",
                "paperId": paper_id,
                "type": "paragraph",
                "text": text,
                "source": {"pageNumber": 1, "bbox": {"x0": 0, "y0": 0, "x1": 10, "y1": 10}},
                "metadata": {"latex": latex} if latex else {},
            }
        ],
    }


def _manifest(paper_id: str, *, assets=None):
    return {
        "paperId": paper_id,
        "schemaVersion": "paper_document_v1",
        "createdAt": "2026-06-01T00:00:00Z",
        "sourceHash": "hash",
        "assets": assets or [],
    }


def _figure_asset(asset_id: str, *, label: str):
    return {
        "assetId": asset_id,
        "paperId": "paper-assets",
        "kind": "figure",
        "fileName": f"assets/{asset_id}.png",
        "mimeType": "image/png",
        "width": 320,
        "height": 180,
        "checksum": "checksum",
        "pageNumber": 1,
        "label": label,
        "caption": "Figure caption",
        "source": {"pageNumber": 1, "bbox": {"x0": 0, "y0": 0, "x1": 10, "y1": 10}},
        "metadata": {},
    }
