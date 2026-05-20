from __future__ import annotations

from enum import Enum


class ScheduleTriggerType(str, Enum):
    MANUAL = "manual"
    DATE = "date"
    INTERVAL = "interval"
    CRON = "cron"
    EVENT = "event"
    WEBHOOK = "webhook"
    SOURCE_HEALTH = "source_health"
    SUBSCRIPTION = "subscription"
