from __future__ import annotations

import argparse
import json
from typing import Any, Callable, Protocol

from business.boards.cross_board.profiles import DAILY_PROFILE_CHOICES
from interfaces.services.subscription_service import DEFAULT_SUBSCRIPTION_STORE_PATH, SubscriptionApplicationService


class SubscriptionServiceFactory(Protocol):
    def __call__(self, *, store_path: str) -> Any:
        ...


def register(subparsers: argparse._SubParsersAction) -> None:
    subscriptions_parser = subparsers.add_parser("subscriptions", help="Manage topic subscriptions")
    subscriptions_subparsers = subscriptions_parser.add_subparsers(
        dest="subscriptions_command",
        required=True,
    )
    create_parser = subscriptions_subparsers.add_parser(
        "create",
        help="Create or update a topic subscription",
    )
    create_parser.add_argument("--topic", required=True, help="Topic to track")
    create_parser.add_argument("--subscription-id", default=None, help="Optional subscription id")
    create_parser.add_argument("--cadence", choices=["daily", "weekly"], default="weekly")
    create_parser.add_argument("--profile", choices=DAILY_PROFILE_CHOICES, default="live-offline")
    create_parser.add_argument("--source-limit", type=int, default=5)
    create_parser.add_argument("--disabled", action="store_true")
    create_parser.add_argument(
        "--metadata",
        action="append",
        default=None,
        help="Metadata key=value; repeat for multiple values",
    )
    _add_store_path(create_parser)
    create_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    create_parser.set_defaults(handler=create_subscription_from_cli)

    list_parser = subscriptions_subparsers.add_parser("list", help="List topic subscriptions")
    list_parser.add_argument("--enabled-only", action="store_true")
    list_parser.add_argument("--cadence", choices=["daily", "weekly"], default=None)
    _add_store_path(list_parser)
    list_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    list_parser.set_defaults(handler=list_subscriptions_from_cli)

    enable_parser = subscriptions_subparsers.add_parser("enable", help="Enable a topic subscription")
    enable_parser.add_argument("subscription_id")
    _add_store_path(enable_parser)
    enable_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    enable_parser.set_defaults(handler=enable_subscription_from_cli)

    disable_parser = subscriptions_subparsers.add_parser("disable", help="Disable a topic subscription")
    disable_parser.add_argument("subscription_id")
    _add_store_path(disable_parser)
    disable_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    disable_parser.set_defaults(handler=disable_subscription_from_cli)

    delete_parser = subscriptions_subparsers.add_parser("delete", help="Delete a topic subscription")
    delete_parser.add_argument("subscription_id")
    _add_store_path(delete_parser)
    delete_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    delete_parser.set_defaults(handler=delete_subscription_from_cli)


add_subscriptions_commands = register


PrintSubscription = Callable[[dict, bool], int]
ParseKeyValues = Callable[[list[str]], dict[str, str]]


def create_subscription_from_cli(args: argparse.Namespace) -> int:
    return create_subscription(
        args,
        subscription_service_factory=SubscriptionApplicationService,
        parse_key_values=parse_key_values,
        print_subscription=print_subscription,
    )


def list_subscriptions_from_cli(args: argparse.Namespace) -> int:
    return list_subscriptions(
        args,
        subscription_service_factory=SubscriptionApplicationService,
    )


def enable_subscription_from_cli(args: argparse.Namespace) -> int:
    return set_subscription_enabled_from_cli(args, enabled=True)


def disable_subscription_from_cli(args: argparse.Namespace) -> int:
    return set_subscription_enabled_from_cli(args, enabled=False)


def set_subscription_enabled_from_cli(args: argparse.Namespace, *, enabled: bool) -> int:
    return set_subscription_enabled(
        args,
        enabled=enabled,
        subscription_service_factory=SubscriptionApplicationService,
        print_subscription=print_subscription,
    )


def delete_subscription_from_cli(args: argparse.Namespace) -> int:
    return delete_subscription(
        args,
        subscription_service_factory=SubscriptionApplicationService,
    )


def create_subscription(
    args: argparse.Namespace,
    *,
    subscription_service_factory: SubscriptionServiceFactory,
    parse_key_values: ParseKeyValues,
    print_subscription: PrintSubscription,
) -> int:
    try:
        subscription = subscription_service_factory(store_path=args.store_path).create_topic_subscription(
            topic=args.topic,
            cadence=args.cadence,
            profile=args.profile,
            source_limit=args.source_limit,
            subscription_id=args.subscription_id,
            enabled=not args.disabled,
            metadata=parse_key_values(args.metadata or []),
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    return print_subscription(subscription.to_dict(), args.json)


def list_subscriptions(
    args: argparse.Namespace,
    *,
    subscription_service_factory: SubscriptionServiceFactory,
) -> int:
    try:
        result = subscription_service_factory(store_path=args.store_path).list_topic_subscriptions(
            enabled_only=args.enabled_only,
            cadence=args.cadence,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"subscription_count={payload['subscription_count']}")
        for item in payload["subscriptions"]:
            state = "enabled" if item["enabled"] else "disabled"
            print(f"- {item['subscription_id']} {state} cadence={item['cadence']} topic={item['topic']}")
    return 0


def set_subscription_enabled(
    args: argparse.Namespace,
    *,
    enabled: bool,
    subscription_service_factory: SubscriptionServiceFactory,
    print_subscription: PrintSubscription,
) -> int:
    try:
        subscription = subscription_service_factory(store_path=args.store_path).set_enabled(
            args.subscription_id,
            enabled=enabled,
        )
    except (KeyError, ValueError) as exc:
        print(str(exc))
        return 1
    return print_subscription(subscription.to_dict(), args.json)


def delete_subscription(
    args: argparse.Namespace,
    *,
    subscription_service_factory: SubscriptionServiceFactory,
) -> int:
    deleted = subscription_service_factory(store_path=args.store_path).delete_topic_subscription(
        args.subscription_id,
    )
    payload = {"subscription_id": args.subscription_id, "deleted": deleted}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"deleted={str(deleted).lower()}")
    return 0


def print_subscription(payload: dict, json_output: bool) -> int:
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        state = "enabled" if payload["enabled"] else "disabled"
        print(f"subscription_id={payload['subscription_id']}")
        print(f"topic={payload['topic']}")
        print(f"cadence={payload['cadence']}")
        print(f"state={state}")
    return 0


def parse_key_values(values: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"invalid metadata '{value}', expected key=value")
        key, parsed_value = value.split("=", 1)
        if not key:
            raise ValueError(f"invalid metadata '{value}', expected key=value")
        parsed[key] = parsed_value
    return parsed


def _add_store_path(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--store-path",
        default=DEFAULT_SUBSCRIPTION_STORE_PATH,
        help="Local JSON subscription store path",
    )


__all__ = [
    "ParseKeyValues",
    "PrintSubscription",
    "SubscriptionServiceFactory",
    "add_subscriptions_commands",
    "create_subscription",
    "create_subscription_from_cli",
    "delete_subscription",
    "delete_subscription_from_cli",
    "disable_subscription_from_cli",
    "enable_subscription_from_cli",
    "list_subscriptions",
    "list_subscriptions_from_cli",
    "parse_key_values",
    "print_subscription",
    "register",
    "set_subscription_enabled",
    "set_subscription_enabled_from_cli",
]
