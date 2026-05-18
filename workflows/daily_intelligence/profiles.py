from __future__ import annotations

import os

PROFILE_LIVE = "live"
PROFILE_LIVE_OFFLINE = "live-offline"
PROFILE_AGENTIC_OFFLINE = "agentic-offline"
PROFILE_AGENTIC_LIVE = "agentic-live"
LEGACY_DAILY_WORKFLOW_ID = "daily-intelligence-live"
AGENTIC_DAILY_WORKFLOW_ID = "daily-intelligence-agentic"
NEWSROOM_DAILY_AGENTIC_ENABLED = "NEWSROOM_DAILY_AGENTIC_ENABLED"
DAILY_PROFILE_CHOICES = (
    PROFILE_LIVE,
    PROFILE_LIVE_OFFLINE,
    PROFILE_AGENTIC_OFFLINE,
    PROFILE_AGENTIC_LIVE,
)
SUPPORTED_DAILY_PROFILES = frozenset(DAILY_PROFILE_CHOICES)


def validate_daily_profile(profile: str) -> None:
    if profile not in SUPPORTED_DAILY_PROFILES:
        raise ValueError(f"unsupported daily intelligence profile: {profile}")


def daily_agentic_enabled(profile: str, *, environ: dict[str, str] | None = None) -> bool:
    validate_daily_profile(profile)
    if profile in {PROFILE_AGENTIC_OFFLINE, PROFILE_AGENTIC_LIVE}:
        return True
    env = os.environ if environ is None else environ
    return _truthy_env(env.get(NEWSROOM_DAILY_AGENTIC_ENABLED))


def _truthy_env(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def daily_workflow_ids() -> tuple[str, str]:
    return (LEGACY_DAILY_WORKFLOW_ID, AGENTIC_DAILY_WORKFLOW_ID)


def is_daily_workflow_id(workflow_id: str | None) -> bool:
    return str(workflow_id or "").strip().lower() in {
        LEGACY_DAILY_WORKFLOW_ID,
        AGENTIC_DAILY_WORKFLOW_ID,
    }
