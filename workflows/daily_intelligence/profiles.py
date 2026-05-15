from __future__ import annotations

PROFILE_LIVE = "live"
PROFILE_LIVE_OFFLINE = "live-offline"
SUPPORTED_DAILY_PROFILES = frozenset({PROFILE_LIVE, PROFILE_LIVE_OFFLINE})


def validate_daily_profile(profile: str) -> None:
    if profile not in SUPPORTED_DAILY_PROFILES:
        raise ValueError(f"unsupported daily intelligence profile: {profile}")
