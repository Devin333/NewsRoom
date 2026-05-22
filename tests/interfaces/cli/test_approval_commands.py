import json

from interfaces.cli import news as news_cli
from interfaces.cli.commands import approvals as approval_commands


def test_news_cli_approval_lifecycle_uses_local_json_store(tmp_path, capsys) -> None:
    store_path = tmp_path / "approvals.json"

    submit_exit = news_cli.main(
        [
            "approvals",
            "submit",
            "--requested-action",
            "publish_report",
            "--risk-level",
            "high",
            "--reason",
            "operator approval required",
            "--payload-json",
            '{"report_id":"report-1"}',
            "--requested-by",
            "worker",
            "--store-path",
            str(store_path),
            "--json",
        ]
    )
    submitted = json.loads(capsys.readouterr().out)
    approval_id = submitted["approval_id"]

    list_exit = news_cli.main(
        [
            "approvals",
            "list",
            "--status",
            "pending",
            "--store-path",
            str(store_path),
            "--json",
        ]
    )
    listed = json.loads(capsys.readouterr().out)

    approve_exit = news_cli.main(
        [
            "approvals",
            "approve",
            approval_id,
            "--decided-by",
            "operator",
            "--reason",
            "ready",
            "--store-path",
            str(store_path),
            "--json",
        ]
    )
    approved = json.loads(capsys.readouterr().out)

    show_exit = news_cli.main(
        [
            "approvals",
            "show",
            approval_id,
            "--store-path",
            str(store_path),
            "--json",
        ]
    )
    shown = json.loads(capsys.readouterr().out)

    assert submit_exit == 0
    assert list_exit == 0
    assert approve_exit == 0
    assert show_exit == 0
    assert listed["approval_count"] == 1
    assert approved["approval"]["status"] == "approved"
    assert approved["approval"]["decision"]["decided_by"] == "operator"
    assert shown["approval"]["status"] == "approved"


def test_news_cli_approval_modify_uses_local_json_store(tmp_path, capsys) -> None:
    store_path = tmp_path / "approvals.json"

    news_cli.main(
        [
            "approvals",
            "submit",
            "--requested-action",
            "send_notification",
            "--payload-json",
            '{"channel":"email"}',
            "--store-path",
            str(store_path),
            "--json",
        ]
    )
    approval_id = json.loads(capsys.readouterr().out)["approval_id"]

    exit_code = news_cli.main(
        [
            "approvals",
            "modify",
            approval_id,
            "--decided-by",
            "operator",
            "--modifications-json",
            '{"channel":"slack"}',
            "--reason",
            "internal first",
            "--store-path",
            str(store_path),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["approval"]["status"] == "modified"
    assert payload["approval"]["decision"]["modifications"] == {"channel": "slack"}


def test_news_cli_approval_resume_context_uses_local_json_store(tmp_path, capsys) -> None:
    store_path = tmp_path / "approvals.json"

    news_cli.main(
        [
            "approvals",
            "submit",
            "--requested-action",
            "continue_agent",
            "--task-id",
            "task-paused",
            "--run-id",
            "run-paused",
            "--store-path",
            str(store_path),
            "--json",
        ]
    )
    approval_id = json.loads(capsys.readouterr().out)["approval_id"]
    news_cli.main(
        [
            "approvals",
            "approve",
            approval_id,
            "--decided-by",
            "operator",
            "--store-path",
            str(store_path),
            "--json",
        ]
    )
    capsys.readouterr()

    exit_code = news_cli.main(
        [
            "approvals",
            "resume-context",
            approval_id,
            "--decision-key",
            "editor_decision",
            "--store-path",
            str(store_path),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["decision_key"] == "editor_decision"
    assert payload["buffer_updates"]["editor_decision"]["approval_id"] == approval_id
    assert payload["resume_metadata"]["approval_run_id"] == "run-paused"
    assert payload["resume_metadata"]["task_id"] == "task-paused"


def test_news_cli_approval_resume_workflow_uses_run_service(tmp_path, capsys, monkeypatch) -> None:
    store_path = tmp_path / "approvals.json"
    checkpoint_store_path = tmp_path / "checkpoints"
    calls = []

    class FakeRunApplicationService:
        def __init__(self, *, artifact_root):
            self.artifact_root = artifact_root

        def resume_from_approval(self, approval_id, **kwargs):
            calls.append(
                {
                    "artifact_root": self.artifact_root,
                    "approval_id": approval_id,
                    **kwargs,
                }
            )
            return _FakeApprovalWorkflowResumeResult(
                approval_id=approval_id,
                run_id=kwargs["run_id"],
            )

    monkeypatch.setattr(approval_commands, "RunApplicationService", FakeRunApplicationService)
    news_cli.main(
        [
            "approvals",
            "submit",
            "--requested-action",
            "continue_agent",
            "--run-id",
            "run-paused",
            "--store-path",
            str(store_path),
            "--json",
        ]
    )
    approval_id = json.loads(capsys.readouterr().out)["approval_id"]
    news_cli.main(
        [
            "approvals",
            "approve",
            approval_id,
            "--decided-by",
            "operator",
            "--store-path",
            str(store_path),
            "--json",
        ]
    )
    capsys.readouterr()

    exit_code = news_cli.main(
        [
            "approvals",
            "resume-workflow",
            approval_id,
            "--workflow-id",
            "test-no-llm",
            "--profile",
            "test-no-llm",
            "--run-id",
            "run-resumed",
            "--decision-key",
            "editor_decision",
            "--store-path",
            str(store_path),
            "--checkpoint-store-path",
            str(checkpoint_store_path),
            "--artifact-root",
            str(tmp_path / "runs"),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["run_id"] == "run-resumed"
    assert payload["status"] == "succeeded"
    assert calls[0]["approval_id"] == approval_id
    assert calls[0]["workflow_id"] == "test-no-llm"
    assert calls[0]["profile"] == "test-no-llm"
    assert calls[0]["decision_key"] == "editor_decision"
    assert calls[0]["checkpoint_store_path"] == str(checkpoint_store_path)
    assert calls[0]["approval_service"].get_approval(approval_id).approval.status.value == "approved"


class _FakeApprovalWorkflowResumeResult:
    def __init__(self, *, approval_id: str, run_id: str) -> None:
        self.approval_id = approval_id
        self.run_id = run_id

    def to_dict(self) -> dict:
        return {
            "approval_context": {"approval_id": self.approval_id},
            "run_result": {
                "run_id": self.run_id,
                "workflow_id": "daily-intelligence-test-no-llm",
                "workflow_version": "0.1.0",
                "status": "succeeded",
                "output": {"ok": True},
                "artifact_dir": None,
                "manifest_path": None,
                "events_path": None,
                "error": None,
                "manifest": {},
            },
            "run_id": self.run_id,
            "workflow_id": "daily-intelligence-test-no-llm",
            "workflow_version": "0.1.0",
            "status": "succeeded",
            "output": {"ok": True},
            "artifact_dir": None,
            "manifest_path": None,
            "events_path": None,
            "error": None,
        }
