from __future__ import annotations

import argparse
import json
from typing import Any, Callable, Protocol


class SubscriptionServiceFactory(Protocol):
    def __call__(self, *, store_path: str) -> Any:
        ...


PrintSubscription = Callable[[dict, bool], int]
ParseKeyValues = Callable[[list[str]], dict[str, str]]


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
