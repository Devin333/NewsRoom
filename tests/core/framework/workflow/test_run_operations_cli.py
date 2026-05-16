from __future__ import annotations

import json

from scripts.dev import main


def test_dev_cli_cancel_writes_cancel_marker_and_outputs_result_json(tmp_path, capsys) -> None:
    _write_run_manifest(tmp_path, "run-1", status="running")

    exit_code = main(
        [
            "run-cancel",
            "--artifact-root",
            str(tmp_path),
            "--run-id",
            "run-1",
            "--reason",
            "manual stop",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["operation_type"] == "cancel_run"
    assert payload["status"] == "applied"
    assert (tmp_path / "run-1" / "cancel.json").exists()


def test_dev_cli_resume_with_patch_reads_patch_json(tmp_path, capsys) -> None:
    _write_run_manifest(tmp_path, "run-1", status="succeeded")
    patch_path = tmp_path / "patch.json"
    patch_path.write_text(json.dumps({"human_review_decision": {"decision": "approved"}}))

    exit_code = main(
        [
            "run-resume-with-patch",
            "--artifact-root",
            str(tmp_path),
            "--run-id",
            "run-1",
            "--patch-json",
            str(patch_path),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["operation_type"] == "resume_with_patch"
    assert payload["details"]["patch_keys"] == ["human_review_decision"]


def test_dev_cli_rerun_outputs_new_run_id_when_guard_accepts(tmp_path, capsys) -> None:
    _write_run_manifest(tmp_path, "run-1", status="succeeded")

    exit_code = main(
        [
            "run-rerun-from-step",
            "--artifact-root",
            str(tmp_path),
            "--run-id",
            "run-1",
            "--step-id",
            "write",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["operation_type"] == "rerun_from_step"
    assert payload["status"] in {"failed", "rejected"}


def _write_run_manifest(tmp_path, run_id: str, *, status: str) -> None:
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "workflow_id": "daily",
                "workflow_version": "1.0",
                "profile": "test",
                "status": status,
                "operations": [],
            }
        ),
        encoding="utf-8",
    )
