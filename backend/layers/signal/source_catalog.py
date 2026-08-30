from __future__ import annotations

SOURCE_CATEGORIES: tuple[str, ...] = (
    "research",
    "open_source",
    "model_platform",
    "official_blog",
    "agent_framework",
    "developer_discussion",
    "engineering_practice",
)

SOURCE_PRIORITIES: tuple[str, ...] = ("p0", "p1", "p2", "p3")

SOURCE_SIGNAL_KINDS: tuple[str, ...] = (
    "paper",
    "paper_digest",
    "benchmark",
    "sota_update",
    "repository_trend",
    "release",
    "issue",
    "pull_request",
    "discussion",
    "model_release",
    "dataset_release",
    "demo_release",
    "model_platform_update",
    "official_release",
    "official_research",
    "product_update",
    "policy_update",
    "framework_release",
    "framework_discussion",
    "issue_hotspot",
    "docs_update",
    "community_discussion",
    "community_trend",
    "user_feedback",
    "product_trend",
    "tutorial",
    "engineering_case",
    "troubleshooting",
    "deployment",
    "developer_article",
)

SOURCE_TRUST_POLICIES: tuple[str, ...] = (
    "official",
    "research",
    "official_project",
    "curated_media",
    "community",
    "mixed",
    "low_confidence",
)


def normalize_source_category(value: object) -> str | None:
    text = _normalize_text(value)
    return text.replace("-", "_") if text is not None else None


def normalize_source_priority(value: object) -> str | None:
    text = _normalize_text(value)
    return text if text is not None else None


def is_valid_source_category(value: object) -> bool:
    normalized = normalize_source_category(value)
    return normalized in SOURCE_CATEGORIES


def is_valid_source_priority(value: object) -> bool:
    normalized = normalize_source_priority(value)
    return normalized in SOURCE_PRIORITIES


def _normalize_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().casefold().replace(" ", "_")
    return text or None
