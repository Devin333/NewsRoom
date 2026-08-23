from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any, Callable

from framework.workers.approval import ApprovalAlreadyDecidedError, ApprovalNotFoundError
from interfaces.cli.commands.dispatch import CommandHandler, call_handler
from interfaces.services.approval_service import DEFAULT_APPROVAL_STORE_PATH, ApprovalApplicationService


APPROVAL_STATUS_CHOICES = ["pending", "approved", "rejected", "modified", "expired", "cancelled"]


def register(subparsers: argparse._SubParsersAction) -> None:
    approvals_parser = subparsers.add_parser("approvals", help="Manage human approvals")
    approvals_subparsers = approvals_parser.add_subparsers(dest="approvals_command", required=True)

    list_parser = approvals_subparsers.add_parser("list", help="List approval requests")
    list_parser.add_argument(
        "--status",
        choices=APPROVAL_STATUS_CHOICES,
        default=None,
        help="Filter by approval status",
    )
    _add_store_path(list_parser)
    list_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    list_parser.set_defaults(handler=list_approvals)

    submit_parser = approvals_subparsers.add_parser("submit", help="Submit an approval request")
    submit_parser.add_argument("--requested-action", required=True, help="Action requiring approval")
    submit_parser.add_argument("--risk-level", default="medium", help="Risk level")
    submit_parser.add_argument("--reason", default=None, help="Reason for approval")
    submit_parser.add_argument("--payload-json", default="{}", help="Approval payload JSON object")
    submit_parser.add_argument("--task-id", default=None, help="Related task id")
    submit_parser.add_argument("--run-id", default=None, help="Related Graph run id")
    submit_parser.add_argument("--requested-by", default=None, help="Requester id")
    submit_parser.add_argument("--expires-at", default=None, help="Optional expiry as ISO datetime")
    submit_parser.add_argument("--metadata-json", default="{}", help="Approval metadata JSON object")
    _add_store_path(submit_parser)
    submit_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    submit_parser.set_defaults(handler=submit_approval)

    show_parser = approvals_subparsers.add_parser("show", help="Show an approval request")
    show_parser.add_argument("approval_id", help="Approval id")
    _add_store_path(show_parser)
    show_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    show_parser.set_defaults(handler=show_approval)

    resume_context_parser = approvals_subparsers.add_parser(
        "resume-context",
        help="Build Graph resume context for a decided approval",
    )
    resume_context_parser.add_argument("approval_id", help="Approval id")
    resume_context_parser.add_argument(
        "--decision-key",
        default="human_review_decision",
        help="DataBuffer key to write the decision payload into",
    )
    _add_store_path(resume_context_parser)
    resume_context_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    resume_context_parser.set_defaults(handler=resume_context)

    approve_parser = approvals_subparsers.add_parser("approve", help="Approve a request")
    _add_decision_arguments(approve_parser)
    approve_parser.set_defaults(handler=approve)

    reject_parser = approvals_subparsers.add_parser("reject", help="Reject a request")
    _add_decision_arguments(reject_parser)
    reject_parser.set_defaults(handler=reject)

    modify_parser = approvals_subparsers.add_parser("modify", help="Approve with modifications")
    modify_parser.add_argument("approval_id", help="Approval id")
    modify_parser.add_argument("--decided-by", required=True, help="Decision maker")
    modify_parser.add_argument("--modifications-json", required=True, help="Modification JSON object")
    modify_parser.add_argument("--reason", default=None, help="Decision reason")
    _add_store_path(modify_parser)
    modify_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    modify_parser.set_defaults(handler=modify)


def list_approvals(args: argparse.Namespace) -> int:
    service = _approval_service(args.store_path)
    result = service.list_approvals(status=args.status)
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"approval_count={payload['approval_count']}")
        for approval in payload["approvals"]:
            print(
                f"- {approval['approval_id']} status={approval['status']} "
                f"action={approval['requested_action']} risk={approval['risk_level']}"
            )
    return 0


def submit_approval(args: argparse.Namespace) -> int:
    service = _approval_service(args.store_path)
    result = service.submit_request(
        requested_action=args.requested_action,
        risk_level=args.risk_level,
        reason=args.reason,
        payload=parse_json_object(args.payload_json),
        task_id=args.task_id,
        run_id=args.run_id,
        requested_by=args.requested_by,
        expires_at=parse_cli_datetime(args.expires_at),
        metadata=parse_json_object(args.metadata_json),
    )
    print_approval_detail(result.to_dict(), json_output=args.json)
    return 0


def show_approval(args: argparse.Namespace) -> int:
    try:
        result = _approval_service(args.store_path).get_approval(args.approval_id)
    except ApprovalNotFoundError as exc:
        print(str(exc))
        return 1
    print_approval_detail(result.to_dict(), json_output=args.json)
    return 0


def resume_context(args: argparse.Namespace) -> int:
    try:
        result = _approval_service(args.store_path).build_resume_context(
            args.approval_id,
            decision_key=args.decision_key,
        )
    except (ApprovalNotFoundError, ValueError) as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"approval_id={payload['approval_id']}")
        print(f"decision_key={payload['decision_key']}")
        print(f"decision={payload['decision_payload']['decision']}")
        print(f"buffer_update_keys={','.join(sorted(payload['buffer_updates']))}")
        approval_run_id = payload["resume_metadata"].get("approval_run_id")
        if approval_run_id:
            print(f"approval_run_id={approval_run_id}")
    return 0


def approve(args: argparse.Namespace) -> int:
    return approval_decision(
        args,
        lambda service: service.approve(
            args.approval_id,
            decided_by=args.decided_by,
            reason=args.reason,
        ),
    )


def reject(args: argparse.Namespace) -> int:
    return approval_decision(
        args,
        lambda service: service.reject(
            args.approval_id,
            decided_by=args.decided_by,
            reason=args.reason,
        ),
    )


def modify(args: argparse.Namespace) -> int:
    return approval_decision(
        args,
        lambda service: service.modify(
            args.approval_id,
            decided_by=args.decided_by,
            modifications=parse_json_object(args.modifications_json),
            reason=args.reason,
        ),
    )


def approval_decision(args: argparse.Namespace, call: Callable[[Any], Any]) -> int:
    try:
        result = call(_approval_service(args.store_path))
    except (ApprovalNotFoundError, ApprovalAlreadyDecidedError, ValueError) as exc:
        print(str(exc))
        return 1
    print_approval_detail(result.to_dict(), json_output=args.json)
    return 0


def print_approval_detail(payload: dict, *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    approval = payload["approval"]
    print(f"approval_id={approval['approval_id']}")
    print(f"status={approval['status']}")
    print(f"requested_action={approval['requested_action']}")
    print(f"risk_level={approval['risk_level']}")


def parse_json_object(value: str) -> dict:
    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise SystemExit("--args-json must be a JSON object")
    return payload


def parse_cli_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError as exc:
        raise SystemExit(f"invalid ISO datetime: {value}") from exc


def _approval_service(store_path: str):
    return ApprovalApplicationService(store_path=store_path)


def _add_store_path(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--store-path",
        default=DEFAULT_APPROVAL_STORE_PATH,
        help="Local JSON approval store path",
    )


def _add_decision_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("approval_id", help="Approval id")
    parser.add_argument("--decided-by", required=True, help="Decision maker")
    parser.add_argument("--reason", default=None, help="Decision reason")
    _add_store_path(parser)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")


add_approvals_commands = register


__all__ = [
    "APPROVAL_STATUS_CHOICES",
    "CommandHandler",
    "add_approvals_commands",
    "approval_decision",
    "approve",
    "call_handler",
    "list_approvals",
    "modify",
    "parse_cli_datetime",
    "parse_json_object",
    "print_approval_detail",
    "register",
    "reject",
    "resume_context",
    "show_approval",
    "submit_approval",
]
