from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from datetime import date, datetime, timezone
from typing import Any

from framework.harness.artifacts import GraphArtifactAlertStatus
from framework.harness.runtime.result_errors import (
    GraphArtifactResultError,
    GraphArtifactResultErrorCode,
    result_error,
)
from interfaces.composition.research_errors import ResearchCompositionError
from interfaces.composition.research_graph_artifacts import (
    build_research_graph_artifact_governance_service,
)


UTC = timezone.utc
DEFAULT_GC_OPERATION_LIMIT = 100


def register(storage_subparsers: argparse._SubParsersAction) -> None:
    graph_parser = storage_subparsers.add_parser(
        "graph-artifacts",
        help="Operate tenant-scoped Graph artifact governance",
    )
    graph_subparsers = graph_parser.add_subparsers(
        dest="storage_graph_artifact_command",
        required=True,
    )

    gc_parser = graph_subparsers.add_parser(
        "gc",
        help="Plan or apply Graph artifact garbage collection",
    )
    gc_subparsers = gc_parser.add_subparsers(
        dest="storage_graph_artifact_gc_command",
        required=True,
    )
    gc_plan_parser = gc_subparsers.add_parser(
        "plan",
        help="Create an exact tenant-scoped GC plan",
    )
    _add_tenant_argument(gc_plan_parser)
    _add_now_argument(gc_plan_parser)
    _add_json_argument(gc_plan_parser)
    gc_plan_parser.set_defaults(handler=graph_artifact_gc_plan)

    gc_apply_parser = gc_subparsers.add_parser(
        "apply",
        help="Apply a previously prepared exact GC plan",
    )
    _add_tenant_argument(gc_apply_parser)
    gc_apply_parser.add_argument("--plan-checksum", required=True)
    gc_apply_parser.add_argument(
        "--max-operations",
        type=int,
        default=DEFAULT_GC_OPERATION_LIMIT,
    )
    gc_apply_parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm lifecycle-authorized physical deletion",
    )
    _add_json_argument(gc_apply_parser)
    gc_apply_parser.set_defaults(handler=graph_artifact_gc_apply)

    cost_parser = graph_subparsers.add_parser(
        "cost",
        help="Generate Graph artifact cost reports",
    )
    cost_subparsers = cost_parser.add_subparsers(
        dest="storage_graph_artifact_cost_command",
        required=True,
    )
    cost_report_parser = cost_subparsers.add_parser(
        "report",
        help="Generate one exact UTC daily cost report",
    )
    _add_tenant_argument(cost_report_parser)
    cost_report_parser.add_argument("--day", required=True, help="UTC day as YYYY-MM-DD")
    _add_now_argument(cost_report_parser)
    _add_json_argument(cost_report_parser)
    cost_report_parser.set_defaults(handler=graph_artifact_cost_report)

    quota_parser = graph_subparsers.add_parser(
        "quota",
        help="Inspect tenant, run, and artifact-class quota",
    )
    _add_tenant_argument(quota_parser)
    _add_now_argument(quota_parser)
    _add_json_argument(quota_parser)
    quota_parser.set_defaults(handler=graph_artifact_quota)

    reconcile_parser = graph_subparsers.add_parser(
        "reconcile",
        help="Inspect tenant-scoped catalog reconciliation",
    )
    _add_tenant_argument(reconcile_parser)
    _add_now_argument(reconcile_parser)
    _add_json_argument(reconcile_parser)
    reconcile_parser.set_defaults(handler=graph_artifact_reconcile)

    alerts_parser = graph_subparsers.add_parser(
        "alerts",
        help="List or acknowledge durable governance alerts",
    )
    alerts_subparsers = alerts_parser.add_subparsers(
        dest="storage_graph_artifact_alert_command",
        required=True,
    )
    alerts_list_parser = alerts_subparsers.add_parser(
        "list",
        help="List tenant-scoped governance alerts",
    )
    _add_tenant_argument(alerts_list_parser)
    alerts_list_parser.add_argument(
        "--status",
        choices=tuple(status.value for status in GraphArtifactAlertStatus),
        default=None,
    )
    _add_json_argument(alerts_list_parser)
    alerts_list_parser.set_defaults(handler=graph_artifact_alerts_list)

    alerts_ack_parser = alerts_subparsers.add_parser(
        "acknowledge",
        help="Compare-and-set acknowledge one governance alert",
    )
    _add_tenant_argument(alerts_ack_parser)
    alerts_ack_parser.add_argument("--alert-id", required=True)
    alerts_ack_parser.add_argument("--expected-checksum", required=True)
    alerts_ack_parser.add_argument("--acknowledged-by", required=True)
    _add_now_argument(alerts_ack_parser)
    _add_json_argument(alerts_ack_parser)
    alerts_ack_parser.set_defaults(handler=graph_artifact_alert_acknowledge)


def graph_artifact_gc_plan(args: argparse.Namespace) -> int:
    return _run(
        lambda service: service.plan_gc(
            tenant_id=args.tenant_id,
            observed_at=_parse_datetime(args.now),
        ),
    )


def graph_artifact_gc_apply(args: argparse.Namespace) -> int:
    if not args.yes:
        return _print_error(
            code="graph_artifact_gc_confirmation_required",
            message="graph artifact gc apply requires --yes",
        )
    return _run(
        lambda service: service.apply_gc(
            tenant_id=args.tenant_id,
            plan_checksum=args.plan_checksum,
            confirmed=True,
            max_operations=args.max_operations,
        ),
    )


def graph_artifact_cost_report(args: argparse.Namespace) -> int:
    return _run(
        lambda service: service.generate_cost_report(
            tenant_id=args.tenant_id,
            day=_parse_day(args.day),
            generated_at=_parse_datetime(args.now),
        ),
    )


def graph_artifact_quota(args: argparse.Namespace) -> int:
    return _run(
        lambda service: service.inspect_quota(
            tenant_id=args.tenant_id,
            captured_at=_parse_datetime(args.now),
        ),
    )


def graph_artifact_reconcile(args: argparse.Namespace) -> int:
    return _run(
        lambda service: service.reconcile(
            tenant_id=args.tenant_id,
            observed_at=_parse_datetime(args.now),
        ),
    )


def graph_artifact_alerts_list(args: argparse.Namespace) -> int:
    return _run(
        lambda service: service.list_alerts(
            tenant_id=args.tenant_id,
            status=(
                GraphArtifactAlertStatus(args.status)
                if args.status is not None
                else None
            ),
        ),
    )


def graph_artifact_alert_acknowledge(args: argparse.Namespace) -> int:
    return _run(
        lambda service: service.acknowledge_alert(
            tenant_id=args.tenant_id,
            alert_id=args.alert_id,
            expected_checksum=args.expected_checksum,
            acknowledged_by=args.acknowledged_by,
            acknowledged_at=_parse_datetime(args.now),
        ),
    )


def _run(operation: Callable[[Any], Any]) -> int:
    try:
        result = operation(build_research_graph_artifact_governance_service())
    except GraphArtifactResultError as exc:
        print(json.dumps({"error": exc.to_event_payload()}, sort_keys=True))
        return 1
    except ResearchCompositionError as exc:
        print(json.dumps({"error": exc.to_public_dict()}, sort_keys=True))
        return 1
    except (TypeError, ValueError):
        return _print_error(
            code="invalid_graph_artifact_governance_request",
            message="graph artifact governance request is invalid",
        )
    print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
    return 0


def _print_error(*, code: str, message: str) -> int:
    print(
        json.dumps(
            {
                "error": {
                    "code": code,
                    "message": message,
                    "retryable": False,
                }
            },
            sort_keys=True,
        )
    )
    return 1


def _parse_day(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field="cost_report.day",
        ) from exc
    if parsed.isoformat() != value:
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field="cost_report.day",
        )
    return parsed


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timezone required")
        return parsed.astimezone(UTC)
    except (TypeError, ValueError) as exc:
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field="governance.now",
        ) from exc


def _add_tenant_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tenant-id", required=True)


def _add_now_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--now", default=None, help="Optional current ISO datetime")


def _add_json_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print exact machine-readable JSON (the default for this group)",
    )


__all__ = [
    "graph_artifact_alert_acknowledge",
    "graph_artifact_alerts_list",
    "graph_artifact_cost_report",
    "graph_artifact_gc_apply",
    "graph_artifact_gc_plan",
    "graph_artifact_quota",
    "graph_artifact_reconcile",
    "register",
]
