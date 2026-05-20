import json
from pathlib import Path

from framework.specs import WorkflowStatus
from business.boards.cross_board.workflows.daily_intelligence import run_test_no_llm


def test_test_no_llm_workflow_produces_deterministic_report_artifacts(tmp_path) -> None:
    result = run_test_no_llm(
        artifact_root=tmp_path,
        request={"topic": "semiconductors"},
        run_id="test-no-llm-success",
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["final_report"]["title"] == (
        "Daily Intelligence Test Report: semiconductors"
    )
    assert result.output["final_report"]["profile"] == "test-no-llm"

    run_dir = Path(result.artifact_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["profile"] == "test-no-llm"
    assert manifest["artifacts"]["report_json"] == "report.json"
    assert manifest["artifacts"]["report_markdown"] == "report.md"

    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["topic"] == "semiconductors"
    assert "Profile: test-no-llm" in (run_dir / "report.md").read_text(encoding="utf-8")


def test_test_no_llm_workflow_is_repeatable_with_same_request(tmp_path) -> None:
    first = run_test_no_llm(
        artifact_root=tmp_path,
        request={"topic": "ai policy"},
        run_id="first",
    )
    second = run_test_no_llm(
        artifact_root=tmp_path,
        request={"topic": "ai policy"},
        run_id="second",
    )

    assert first.output["final_report"] == second.output["final_report"]
    assert first.output["report_markdown"] == second.output["report_markdown"]
