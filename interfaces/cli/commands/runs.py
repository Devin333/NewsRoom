from __future__ import annotations

import argparse
import json
from typing import Any

from interfaces.cli.commands.dispatch import CommandHandler, call_handler


def register(subparsers: argparse._SubParsersAction) -> None:
    runs_parser = subparsers.add_parser("runs", help="Inspect workflow run history")
    runs_subparsers = runs_parser.add_subparsers(dest="runs_command", required=True)

    list_parser = runs_subparsers.add_parser("list", help="List local runs")
    list_parser.add_argument("--limit", type=int, default=20, help="Maximum runs")
    _add_artifact_root_argument(list_parser)
    list_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    list_parser.set_defaults(handler=list_runs)

    show_parser = runs_subparsers.add_parser("show", help="Show a local run manifest")
    show_parser.add_argument("run_id", help="Run id")
    _add_artifact_root_argument(show_parser)
    show_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    show_parser.set_defaults(handler=show_run)

    events_parser = runs_subparsers.add_parser("events", help="Show local run events")
    events_parser.add_argument("run_id", help="Run id")
    _add_artifact_root_argument(events_parser)
    events_parser.add_argument("--limit", type=int, default=None, help="Maximum events")
    events_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    events_parser.add_argument("--sse", action="store_true", help="Print Server-Sent Events frames")
    events_parser.set_defaults(handler=run_events)

    replay_parser = runs_subparsers.add_parser("replay", help="Build a run replay bundle")
    replay_parser.add_argument("run_id", help="Run id")
    _add_artifact_root_argument(replay_parser)
    replay_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    replay_parser.set_defaults(handler=replay_run)

    diagnostics_parser = runs_subparsers.add_parser(
        "diagnostics",
        help="Inspect run diagnostics",
    )
    diagnostics_parser.add_argument("run_id", help="Run id")
    _add_artifact_root_argument(diagnostics_parser)
    diagnostics_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    diagnostics_parser.set_defaults(handler=run_diagnostics)

    health_parser = runs_subparsers.add_parser("health", help="Inspect run health")
    health_parser.add_argument("run_id", help="Run id")
    _add_artifact_root_argument(health_parser)
    health_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    health_parser.set_defaults(handler=run_health)

    catalog_health_parser = runs_subparsers.add_parser(
        "catalog-health",
        help="Inspect run catalog health",
    )
    _add_artifact_root_argument(catalog_health_parser)
    catalog_health_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    catalog_health_parser.set_defaults(handler=run_catalog_health)

    compare_parser = runs_subparsers.add_parser("compare", help="Compare two workflow runs")
    compare_parser.add_argument("base_run_id", help="Base run id")
    compare_parser.add_argument("target_run_id", help="Target run id")
    _add_artifact_root_argument(compare_parser)
    compare_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    compare_parser.set_defaults(handler=compare_runs)

    artifacts_parser = runs_subparsers.add_parser("artifacts", help="List artifacts for a run")
    artifacts_parser.add_argument("run_id", help="Run id")
    _add_artifact_root_argument(artifacts_parser)
    artifacts_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    artifacts_parser.set_defaults(handler=run_artifacts)

    cancel_parser = runs_subparsers.add_parser("cancel", help="Request cancellation for a run")
    cancel_parser.add_argument("run_id", help="Run id")
    cancel_parser.add_argument("--reason", required=True, help="Reason for cancellation")
    cancel_parser.add_argument("--actor-id", default=None, help="Optional actor id")
    _add_artifact_root_argument(cancel_parser)
    cancel_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    cancel_parser.set_defaults(handler=cancel_run)

    rerun_parser = runs_subparsers.add_parser(
        "rerun-from-step",
        help="Request a rerun starting from one workflow step",
    )
    rerun_parser.add_argument("run_id", help="Run id")
    rerun_parser.add_argument("step_id", help="Step id")
    rerun_parser.add_argument("--actor-id", default=None, help="Optional actor id")
    _add_artifact_root_argument(rerun_parser)
    rerun_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    rerun_parser.set_defaults(handler=rerun_from_step)


def list_runs(args: argparse.Namespace) -> int:
    result = _run_inspection_service(args.artifact_root).list_runs(limit=args.limit)
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"run_count={payload['run_count']}")
        for run in payload["runs"]:
            print(f"- {run['run_id']} status={run['status']} profile={run['profile']}")
            print(f"  started_at={run['started_at']} manifest={run['manifest_path']}")
    return 0


def show_run(args: argparse.Namespace) -> int:
    try:
        result = _run_inspection_service(args.artifact_root).get_run(args.run_id)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        manifest = payload["manifest"]
        print(f"run_id={payload['run_id']}")
        print(f"status={manifest.get('status')}")
        print(f"workflow_id={manifest.get('workflow_id')}")
        print(f"profile={manifest.get('profile')}")
        print(f"manifest_path={payload['manifest_path']}")
    return 0


def run_events(args: argparse.Namespace) -> int:
    try:
        result = _run_inspection_service(args.artifact_root).get_run_events(
            args.run_id,
            limit=args.limit,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    elif args.sse:
        for frame in run_events_sse_frames(payload):
            print(frame, end="")
    else:
        print(f"run_id={payload['run_id']}")
        print(f"event_count={payload['event_count']}")
        for event in payload["events"]:
            print(f"- {event.get('event_type')} at {event.get('occurred_at')}")
    return 0


def run_events_sse_frames(payload: dict[str, Any]):
    run_id = str(payload.get("run_id") or "")
    for index, event in enumerate(payload.get("events") or []):
        event_payload = event if isinstance(event, dict) else {}
        event_type = str(event_payload.get("event_type") or "run.event")
        yield sse_frame(
            event_type,
            {
                "run_id": run_id,
                "sequence": index,
                "event": event_payload,
            },
        )
    yield sse_frame(
        "run.events.done",
        {
            "run_id": run_id,
            "event_count": int(payload.get("event_count") or 0),
            "events_path": payload.get("events_path"),
        },
    )


def sse_frame(event_name: str, data: dict[str, Any]) -> str:
    return (
        f"event: {event_name}\n"
        f"data: {json.dumps(data, ensure_ascii=False, sort_keys=True)}\n\n"
    )


def replay_run(args: argparse.Namespace) -> int:
    try:
        result = _run_inspection_service(args.artifact_root).replay_run(args.run_id)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        manifest = payload["manifest"]
        print(f"run_id={payload['run_id']}")
        print(f"status={manifest.get('status')}")
        print(f"manifest_path={payload['manifest_path']}")
        print(f"event_count={payload['event_count']}")
        if payload["events_error"]:
            print(f"events_error={payload['events_error']}")
        print(f"artifact_count={payload['artifact_count']}")
        for artifact in payload["artifacts"]:
            line = (
                f"- {artifact['artifact_key']} path={artifact['relative_path']} "
                f"type={artifact['content_type']} size={artifact['size_bytes']}"
            )
            if artifact["read_error"]:
                line = f"{line} error={artifact['read_error']}"
            print(line)
    return 0


def run_diagnostics(args: argparse.Namespace) -> int:
    try:
        result = _run_inspection_service(args.artifact_root).get_run_diagnostics(args.run_id)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        diagnostics = payload["diagnostics"]
        health = diagnostics.get("health_report") or {}
        timeline_summary = diagnostics.get("timeline_summary") or {}
        artifact_inventory = diagnostics.get("artifact_inventory") or {}
        print(f"run_id={payload['run_id']}")
        print(f"healthy={str(diagnostics.get('healthy')).lower()}")
        print(f"health_severity={health.get('severity')}")
        print(f"event_count={timeline_summary.get('event_count')}")
        print(f"artifact_count={artifact_inventory.get('artifact_count')}")
        print(f"missing_artifacts={artifact_inventory.get('missing_count')}")
    return 0


def run_health(args: argparse.Namespace) -> int:
    try:
        result = _run_inspection_service(args.artifact_root).get_run_health(args.run_id)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        health = payload["health"]
        print(f"run_id={payload['run_id']}")
        print(f"severity={health.get('severity')}")
        print(f"healthy={str(health.get('healthy')).lower()}")
        print(f"summary={health.get('summary')}")
        print(f"failed_steps={','.join(health.get('failed_steps') or [])}")
        for warning in health.get("warnings") or []:
            print(f"warning={warning}")
    return 0


def run_catalog_health(args: argparse.Namespace) -> int:
    result = _run_inspection_service(args.artifact_root).get_catalog_health()
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        health = payload["health"]
        print(f"severity={health.get('severity')}")
        print(f"healthy={str(health.get('healthy')).lower()}")
        print(f"run_count={health.get('run_count')}")
        print(f"failed_count={health.get('failed_count')}")
        print(f"paused_count={health.get('paused_count')}")
        print(f"latest_run_id={health.get('latest_run_id')}")
        for warning in health.get("warnings") or []:
            print(f"warning={warning}")
    return 0


def compare_runs(args: argparse.Namespace) -> int:
    try:
        result = _run_inspection_service(args.artifact_root).compare_runs(
            args.base_run_id,
            args.target_run_id,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        comparison = payload["comparison"]
        print(f"base_run_id={payload['base_run_id']}")
        print(f"target_run_id={payload['target_run_id']}")
        print(f"same_workflow={str(comparison.get('same_workflow')).lower()}")
        print(f"status_changed={str(comparison.get('status_changed')).lower()}")
        print(f"workflow_version_changed={str(comparison.get('workflow_version_changed')).lower()}")
        print(f"has_behavioral_change={str(comparison.get('has_behavioral_change')).lower()}")
    return 0


def run_artifacts(args: argparse.Namespace) -> int:
    try:
        result = _artifact_service(args.artifact_root).list_artifacts(args.run_id)
    except FileNotFoundError as exc:
        print(str(exc))
        return 3
    except ValueError as exc:
        print(str(exc))
        return 2
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"run_id={payload['run_id']}")
        print(f"artifact_count={payload['artifact_count']}")
        for artifact in payload["artifacts"]:
            print(
                f"- {artifact['artifact_key']} path={artifact['relative_path']} "
                f"type={artifact['content_type']} size={artifact['size_bytes']}"
            )
    return 0


def cancel_run(args: argparse.Namespace) -> int:
    try:
        result = _run_operation_service(args.artifact_root).cancel_run(
            args.run_id,
            reason=args.reason,
            actor_id=args.actor_id,
        )
    except FileNotFoundError as exc:
        print(str(exc))
        return 3
    except ValueError as exc:
        print(str(exc))
        return 2
    return print_run_operation_result(result.to_dict(), json_output=args.json)


def rerun_from_step(args: argparse.Namespace) -> int:
    try:
        result = _run_operation_service(args.artifact_root).rerun_from_step(
            args.run_id,
            step_id=args.step_id,
            actor_id=args.actor_id,
        )
    except FileNotFoundError as exc:
        print(str(exc))
        return 3
    except ValueError as exc:
        print(str(exc))
        return 2
    return print_run_operation_result(result.to_dict(), json_output=args.json)


def print_run_operation_result(payload: dict[str, Any], *, json_output: bool) -> int:
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"operation_id={payload['operation_id']}")
        print(f"operation_type={payload['operation_type']}")
        print(f"status={payload['status']}")
        print(f"run_id={payload['run_id']}")
        if payload.get("new_run_id"):
            print(f"new_run_id={payload['new_run_id']}")
        print(f"message={payload['message']}")
    return 0 if payload.get("status") in {"accepted", "applied"} else 1


def _run_inspection_service(artifact_root: str):
    news_cli = _news_cli()

    return news_cli.RunInspectionService(artifact_root=artifact_root)


def _artifact_service(artifact_root: str):
    news_cli = _news_cli()

    return news_cli.ArtifactInspectionService(artifact_root=artifact_root)


def _run_operation_service(artifact_root: str):
    news_cli = _news_cli()

    return news_cli.RunOperationApplicationService(artifact_root=artifact_root)


def _news_cli():
    from interfaces.cli import news as news_cli

    return news_cli


def _add_artifact_root_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--artifact-root",
        default=".newsroom/runs",
        help="Directory where run artifacts are stored",
    )


add_runs_commands = register


__all__ = [
    "CommandHandler",
    "add_runs_commands",
    "call_handler",
    "cancel_run",
    "compare_runs",
    "list_runs",
    "print_run_operation_result",
    "register",
    "replay_run",
    "rerun_from_step",
    "run_artifacts",
    "run_catalog_health",
    "run_diagnostics",
    "run_events",
    "run_events_sse_frames",
    "run_health",
    "show_run",
    "sse_frame",
]
