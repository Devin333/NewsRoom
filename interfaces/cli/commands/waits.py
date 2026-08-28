from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Callable

from interfaces.sdk import NewsApiError, NewsClient


def register(subparsers: argparse._SubParsersAction) -> None:
    waits_parser = subparsers.add_parser("waits", help="Inspect and signal Graph Waits")
    waits_subparsers = waits_parser.add_subparsers(dest="waits_command", required=True)

    inspect_parser = waits_subparsers.add_parser("inspect", help="Inspect a Graph Wait")
    _add_wait_identity_arguments(inspect_parser)
    inspect_parser.set_defaults(handler=inspect_wait)

    signal_parser = waits_subparsers.add_parser("signal", help="Deliver a bounded Wait signal")
    _add_wait_identity_arguments(signal_parser)
    signal_parser.add_argument("--signal-id", required=True, help="Durable signal id")
    signal_parser.add_argument("--signal-schema-ref", required=True, help="Exact signal schema ref")
    signal_parser.add_argument("--correlation-json", required=True, help="Correlation JSON object")
    signal_parser.add_argument("--payload-ref", required=True, help="Content-addressed payload ref")
    signal_parser.set_defaults(handler=deliver_signal)

    cancel_parser = waits_subparsers.add_parser("cancel", help="Cancel a Graph Wait")
    _add_wait_identity_arguments(cancel_parser)
    cancel_parser.add_argument("--cancellation-id", required=True, help="Durable cancellation id")
    cancel_parser.add_argument("--reason-code", required=True, help="Bounded cancellation reason code")
    cancel_parser.set_defaults(handler=cancel_wait)

    approval_parser = subparsers.add_parser(
        "approval-decision",
        help="Submit an approval decision for a Graph Wait",
    )
    _add_wait_identity_arguments(approval_parser)
    approval_parser.add_argument("--approval-id", required=True, help="Durable approval id")
    decision = approval_parser.add_mutually_exclusive_group(required=True)
    decision.add_argument("--approve", action="store_true", help="Approve the durable Wait")
    decision.add_argument("--reject", action="store_true", help="Reject the durable Wait")
    approval_parser.set_defaults(handler=approval_decision)


def inspect_wait(args: argparse.Namespace) -> int:
    return _run_request(
        args,
        lambda client: client.waits.inspect(args.run_id, args.node_instance_id),
    )


def deliver_signal(args: argparse.Namespace) -> int:
    return _run_request(
        args,
        lambda client: client.waits.deliver_signal(
            args.run_id,
            args.node_instance_id,
            signal_id=args.signal_id,
            signal_schema_ref=args.signal_schema_ref,
            correlation=_parse_json_object(args.correlation_json, "--correlation-json"),
            payload_ref=args.payload_ref,
        ),
    )


def approval_decision(args: argparse.Namespace) -> int:
    return _run_request(
        args,
        lambda client: client.waits.decide_approval(
            args.run_id,
            args.node_instance_id,
            approval_id=args.approval_id,
            approved=bool(args.approve),
        ),
    )


def cancel_wait(args: argparse.Namespace) -> int:
    return _run_request(
        args,
        lambda client: client.waits.cancel(
            args.run_id,
            args.node_instance_id,
            cancellation_id=args.cancellation_id,
            reason_code=args.reason_code,
        ),
    )


def _run_request(args: argparse.Namespace, operation: Callable[[NewsClient], dict[str, Any]]) -> int:
    try:
        payload = operation(_client(args))
    except (NewsApiError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return _error_exit_code(exc)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        _print_human_wait(payload)
    return 0


def _client(args: argparse.Namespace) -> NewsClient:
    return NewsClient(
        args.base_url,
        api_key=args.api_key,
        timeout=args.timeout,
    )


def _add_wait_identity_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("run_id", help="Graph run id")
    parser.add_argument("node_instance_id", help="Exact Graph node instance id")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("NEWSROOM_API_URL", "http://127.0.0.1:8000"),
        help="Agora Hub API base URL",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("NEWSROOM_API_KEY"),
        help="Bearer API key (or NEWSROOM_API_KEY)",
    )
    parser.add_argument("--timeout", type=float, default=30, help="HTTP timeout in seconds")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")


def _parse_json_object(value: str, option: str) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{option} must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{option} must be a JSON object")
    return payload


def _print_human_wait(payload: dict[str, Any]) -> None:
    wait = payload.get("wait") if isinstance(payload.get("wait"), dict) else payload
    for key in (
        "operation",
        "run_id",
        "node_instance_id",
        "wait_id",
        "kind",
        "status",
        "lifecycle",
        "outcome",
        "graph_id",
        "graph_version",
        "graph_ref",
        "graph_checksum",
    ):
        if key in payload and key == "operation":
            print(f"{key}={payload[key]}")
        elif key in wait:
            print(f"{key}={wait[key]}")


def _error_exit_code(exc: Exception) -> int:
    status_code = getattr(exc, "status_code", None)
    if status_code is not None and int(status_code) >= 500:
        return 2
    return 1


add_wait_commands = register


__all__ = [
    "add_wait_commands",
    "approval_decision",
    "cancel_wait",
    "deliver_signal",
    "inspect_wait",
    "register",
]
