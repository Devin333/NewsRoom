"""Canonical taxonomy categories for paper radar classification."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence


AI_TASK_GROUPS: tuple[str, ...] = (
    "agents",
    "language-models",
    "reasoning",
    "multimodal",
    "computer-vision",
    "speech-audio",
    "code-ai",
    "robotics-embodied",
    "retrieval-knowledge",
    "data-evaluation",
    "systems-infra",
    "security-safety",
    "ai-for-science",
    "human-ai-interaction",
)

BENCHMARK_CATEGORIES: tuple[str, ...] = (
    "language-understanding",
    "language-generation",
    "question-answering",
    "reasoning-math",
    "reasoning-logic",
    "long-context",
    "instruction-following",
    "alignment-preference",
    "agent-task-completion",
    "tool-use",
    "code-generation",
    "software-engineering",
    "retrieval-search",
    "knowledge-graph",
    "image-classification",
    "object-detection",
    "segmentation",
    "image-generation",
    "video-understanding",
    "video-generation",
    "visual-question-answering",
    "multimodal-reasoning",
    "ocr-document-understanding",
    "speech-recognition",
    "speech-generation",
    "audio-understanding",
    "music-generation",
    "robotics-manipulation",
    "robotics-navigation",
    "embodied-control",
    "medical-imaging",
    "biomedical-nlp",
    "scientific-discovery",
    "time-series-forecasting",
    "graph-learning",
    "recommendation-ranking",
    "safety-robustness",
    "privacy-security",
    "efficiency-systems",
    "data-quality-evaluation",
)

FALLBACK_PWC_METHOD_COLLECTIONS: tuple[str, ...] = (
    "Transformers",
    "Attention Mechanisms",
    "Language Models",
    "Diffusion Models",
    "Object Detection Models",
    "Convolutional Neural Networks",
    "Graph Models",
    "Reinforcement Learning",
    "Representation Learning",
    "Optimization",
)


def load_pwc_method_collections(path: str | Path | None = None) -> tuple[str, ...]:
    """Load Papers with Code method collection names from project data."""

    return _load_pwc_method_collections(str(Path(path).resolve()) if path else "")


@lru_cache(maxsize=8)
def _load_pwc_method_collections(path_key: str) -> tuple[str, ...]:
    path = Path(path_key) if path_key else _project_root() / "data" / "papers" / "pwc-method-collections.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return FALLBACK_PWC_METHOD_COLLECTIONS

    collections = payload.get("collections") if isinstance(payload, Mapping) else None
    names: list[str] = []
    seen: set[str] = set()
    for item in _sequence(collections):
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, Mapping):
            name = str(item.get("name") or item.get("collection") or "").strip()
        else:
            continue
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return tuple(names) or FALLBACK_PWC_METHOD_COLLECTIONS


def normalize_ai_task_group(value: Any) -> str | None:
    """Normalize an AI task group slug."""

    return _normalize_enum(value, AI_TASK_GROUPS)


def normalize_benchmark_category(value: Any) -> str | None:
    """Normalize a benchmark category slug."""

    return _normalize_enum(value, BENCHMARK_CATEGORIES)


def normalize_method_collection(value: Any, *, collections: Sequence[str] | None = None) -> str | None:
    """Normalize a Papers with Code method collection name."""

    text = _text(value)
    if not text:
        return None
    candidates = collections or load_pwc_method_collections()
    by_name = {item.casefold(): item for item in candidates}
    by_slug = {_slugify(item): item for item in candidates}
    return by_name.get(text.casefold()) or by_slug.get(_slugify(text))


def task_group_options() -> list[Mapping[str, str]]:
    """Return public task group option records."""

    return [{"slug": group, "name": _title_from_slug(group)} for group in AI_TASK_GROUPS]


def benchmark_category_options() -> list[Mapping[str, str]]:
    """Return public benchmark category option records."""

    return [{"slug": category, "name": _title_from_slug(category)} for category in BENCHMARK_CATEGORIES]


def method_collection_options(collections: Sequence[str] | None = None) -> list[Mapping[str, str]]:
    """Return public method collection option records."""

    return [{"slug": _slugify(name), "name": name} for name in (collections or load_pwc_method_collections())]


def _normalize_enum(value: Any, allowed: Sequence[str]) -> str | None:
    text = _text(value)
    if not text:
        return None
    allowed_set = set(allowed)
    if text in allowed_set:
        return text
    slug = _slugify(text)
    return slug if slug in allowed_set else None


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _title_from_slug(value: str) -> str:
    return " ".join(part.upper() if part in {"ai", "nlp", "ocr"} else part.capitalize() for part in value.split("-"))


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]
