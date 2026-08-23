from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from framework.agent.artifacts import (
    ArtifactChecksumMismatchError,
    ArtifactPathError,
    ArtifactStoreMetadataError,
    ArtifactStoreRequiredError,
)
from framework.events.errors import EventStoreUnavailableError
from interfaces.cli.commands.dispatch import CommandHandler, call_handler
from interfaces.services.artifact_service import ArtifactInspectionService
from interfaces.services.run_inspection_factory import graph_run_inspection_service_from_env
from interfaces.services.run_event_sse import run_events_sse_frames


def register(subparsers: argparse._SubParsersAction) -> None:
    runs_parser = subparsers.add_parser("runs", help="Inspect Graph run history")
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
    events_parser.add_argument("--offset", type=int, default=0, help="Legacy pagination position")
    events_parser.add_argument("--event-type", default=None, help="Filter by event type")
    events_parser.add_argument(
        "--node-instance-id",
        default=None,
        help="Filter by exact Graph node instance",
    )
    events_parser.add_argument(
        "--sequence-cursor",
        default=None,
        help="Opaque durable sequence cursor returned by the previous page",
    )
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

    compare_parser = runs_subparsers.add_parser("compare", help="Compare two Graph runs")
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


def list_runs(args: argparse.Namespace) -> int:
    result = _run_inspection_service(args.artifact_root).list_runs(limit=args.limit)
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"run_count={payload['run_count']}")
        for run in payload["runs"]:
            print(
                f"- {run['run_id']} status={run['status']} "
                f"graph={run.get('graph_id')}@{run.get('graph_version')}"
            )
            print(f"  started_at={run['started_at']} manifest={run['manifest_path']}")
    return 0


def show_run(args: argparse.Namespace) -> int:
    try:
        result = _run_inspection_service(args.artifact_root).get_run(args.run_id)
    except _TYPED_ARTIFACT_ERRORS as exc:
        return _print_typed_artifact_error(exc)
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
        print(f"graph_id={manifest.get('graph_id')}")
        print(f"graph_version={manifest.get('graph_version')}")
        print(f"manifest_path={payload['manifest_path']}")
    return 0


def run_events(args: argparse.Namespace) -> int:
    try:
        event_kwargs: dict[str, Any] = {"limit": args.limit}
        if args.offset:
            event_kwargs["offset"] = args.offset
        if args.event_type is not None:
            event_kwargs["event_type"] = args.event_type
        if args.node_instance_id is not None:
            event_kwargs["node_instance_id"] = args.node_instance_id
        if args.sequence_cursor is not None:
            event_kwargs["sequence_cursor"] = args.sequence_cursor
        result = _run_inspection_service(args.artifact_root).get_run_events(
            args.run_id,
            **event_kwargs,
        )
    except _TYPED_ARTIFACT_ERRORS as exc:
        return _print_typed_artifact_error(exc)
    except EventStoreUnavailableError as exc:
        print(f"availability=unavailable error_type={type(exc).__name__}", file=sys.stderr)
        return 2
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
        print(f"source={payload.get('source')}")
        print(f"availability={payload.get('availability')}")
        print(f"projection_status={payload.get('projection_status')}")
        print(f"high_watermark={payload.get('high_watermark')}")
        print(f"next_sequence_cursor={payload.get('next_sequence_cursor')}")
        for event in payload["events"]:
            print(f"- {event.get('event_type')} at {event.get('occurred_at')}")
    return 2 if payload.get("availability") == "unavailable" else 0


def replay_run(args: argparse.Namespace) -> int:
    try:
        result = _run_inspection_service(args.artifact_root).replay_run(args.run_id)
    except _TYPED_ARTIFACT_ERRORS as exc:
        return _print_typed_artifact_error(exc)
    except EventStoreUnavailableError:
        return _print_event_store_unavailable()
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
            if artifact.get("read_error"):
                line = f"{line} error={artifact['read_error']}"
            print(line)
    return 0


def run_diagnostics(args: argparse.Namespace) -> int:
    try:
        result = _run_inspection_service(args.artifact_root).get_run_diagnostics(args.run_id)
    except _TYPED_ARTIFACT_ERRORS as exc:
        return _print_typed_artifact_error(exc)
    except EventStoreUnavailableError:
        return _print_event_store_unavailable()
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
    except _TYPED_ARTIFACT_ERRORS as exc:
        return _print_typed_artifact_error(exc)
    except EventStoreUnavailableError:
        return _print_event_store_unavailable()
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
    except _TYPED_ARTIFACT_ERRORS as exc:
        return _print_typed_artifact_error(exc)
    except EventStoreUnavailableError:
        return _print_event_store_unavailable()
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
        print(f"same_graph={str(comparison.get('same_graph')).lower()}")
        print(f"base_status={comparison.get('base_status')}")
        print(f"target_status={comparison.get('target_status')}")
        print(f"base_manifest_hash={comparison.get('base_manifest_hash')}")
        print(f"target_manifest_hash={comparison.get('target_manifest_hash')}")
    return 0


def run_artifacts(args: argparse.Namespace) -> int:
    try:
        result = _artifact_service(args.artifact_root).list_artifacts(args.run_id)
    except _TYPED_ARTIFACT_ERRORS as exc:
        return _print_typed_artifact_error(exc)
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


def _run_inspection_service(artifact_root: str):
    return graph_run_inspection_service_from_env(artifact_root=artifact_root)


def _artifact_service(artifact_root: str):
    return ArtifactInspectionService(artifact_root=artifact_root)


def _add_artifact_root_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--artifact-root",
        default=".newsroom/runs",
        help="Directory where run artifacts are stored",
    )


def _print_typed_artifact_error(exc: Exception) -> int:
    print(str(exc), file=sys.stderr)
    return 1


def _print_event_store_unavailable() -> int:
    print(
        "availability=unavailable error_type=EventStoreUnavailableError",
        file=sys.stderr,
    )
    return 2


_TYPED_ARTIFACT_ERRORS = (
    ArtifactPathError,
    ArtifactChecksumMismatchError,
    ArtifactStoreMetadataError,
    ArtifactStoreRequiredError,
)


add_runs_commands = register


__all__ = [
    "CommandHandler",
    "add_runs_commands",
    "call_handler",
    "compare_runs",
    "list_runs",
    "register",
    "replay_run",
    "run_artifacts",
    "run_catalog_health",
    "run_diagnostics",
    "run_events",
    "run_events_sse_frames",
    "run_health",
    "show_run",
]
