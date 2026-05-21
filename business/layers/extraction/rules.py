from __future__ import annotations

import re
from typing import Any, Callable, TypeVar
from urllib.parse import urlsplit

from business.foundation import (
    Confidence,
    Entity,
    EntityType,
    Signal,
    TechnologyCategory,
    build_stable_id,
    canonicalize_url,
    normalize_key,
)


TECH_KEYWORD_MAP: dict[str, tuple[TechnologyCategory, str]] = {
    "agent memory": (TechnologyCategory.MEMORY, "memory"),
    "long-term memory": (TechnologyCategory.MEMORY, "memory"),
    "retrieval augmented generation": (TechnologyCategory.RAG, "rag"),
    "retrieval-augmented generation": (TechnologyCategory.RAG, "rag"),
    "graphrag": (TechnologyCategory.RAG, "rag"),
    "function calling": (TechnologyCategory.TOOL_USE, "tool use"),
    "tool calling": (TechnologyCategory.TOOL_USE, "tool use"),
    "agentic workflow": (TechnologyCategory.WORKFLOW, "workflow"),
    "workflow orchestration": (TechnologyCategory.WORKFLOW, "workflow"),
    "model serving": (TechnologyCategory.MODEL_SERVING, "model serving"),
    "inference serving": (TechnologyCategory.MODEL_SERVING, "model serving"),
    "fine-tuning": (TechnologyCategory.FINE_TUNING, "fine tuning"),
    "finetuning": (TechnologyCategory.FINE_TUNING, "fine tuning"),
    "benchmark": (TechnologyCategory.BENCHMARK, "benchmark"),
    "evaluation": (TechnologyCategory.EVALUATION, "evaluation"),
    "rag": (TechnologyCategory.RAG, "rag"),
    "memory": (TechnologyCategory.MEMORY, "memory"),
    "planning": (TechnologyCategory.PLANNING, "planning"),
    "tool use": (TechnologyCategory.TOOL_USE, "tool use"),
}

TOPIC_KEYWORDS: dict[str, str] = {
    "ai agent": "ai agent",
    "agents": "ai agent",
    "agentic": "ai agent",
    "rag": "rag",
    "llmops": "llmops",
    "multimodal": "multimodal",
    "ai coding": "ai coding",
    "coding agent": "ai coding",
    "evaluation": "evaluation",
    "memory": "memory",
    "planning": "planning",
    "tool use": "tool use",
    "workflow": "workflow",
}

COMPANY_HINTS = {
    "openai",
    "anthropic",
    "google",
    "deepmind",
    "microsoft",
    "meta",
    "nvidia",
    "amazon",
    "apple",
    "hugging face",
    "xai",
    "qwen",
    "cohere",
}

KNOWN_MODEL_HINTS = {
    "gpt-5",
    "gpt-4",
    "claude",
    "gemini",
    "qwen",
    "llama",
    "mistral",
    "deepseek",
}

T = TypeVar("T")


def signal_text(signal: Signal) -> str:
    parts = [signal.title, signal.summary or "", signal.content or "", " ".join(signal.tags), " ".join(signal.authors)]
    return " ".join(part for part in parts if part).casefold()


def github_repo_from_signal(signal: Signal) -> str | None:
    url = signal.url or signal.source.source_url or ""
    path = urlsplit(url).path.strip("/")
    parts = path.split("/")
    if len(parts) >= 2:
        owner, repo = parts[0], parts[1]
        if owner and repo:
            return f"{owner.casefold()}/{repo.casefold()}"
    match = re.search(r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", signal.title.strip())
    if match:
        return f"{match.group(1).casefold()}/{match.group(2).casefold()}"
    return None


def paper_id_from_signal(signal: Signal) -> str | None:
    url = signal.url or ""
    path = urlsplit(url).path.strip("/")
    if "/abs/" in url and path:
        return path.split("/")[-1].casefold()
    match = re.search(r"\b(arxiv:)?(\d{4}\.\d{4,5}(?:v\d+)?)\b", f"{signal.title} {signal.summary or ''}", re.I)
    if match:
        return match.group(2).casefold()
    return None


def titleize_technology(normalized: str) -> str:
    cleaned = normalized.replace("_", " ").strip()
    return " ".join(word.capitalize() for word in cleaned.split())


def canonical_name(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).strip())


def clean_strings(values: list[str]) -> list[str]:
    return [text for text in (str(value).strip() for value in values) if text]


def dedupe_by_key(items: list[T], *, key: Callable[[T], str]) -> list[T]:
    seen: set[str] = set()
    result: list[T] = []
    for item in items:
        marker = key(item)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(item)
    return result


def build_entity(
    *,
    entity_type: EntityType,
    canonical_name_value: str,
    source_signal_id: str,
    confidence: float,
    url: str | None = None,
    aliases: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Entity:
    normalized_key = normalize_key(canonical_name_value)
    return Entity(
        entity_id=build_stable_id("entity", entity_type.value, normalized_key),
        entity_type=entity_type,
        canonical_name=canonical_name(canonical_name_value),
        aliases=clean_strings(aliases or []),
        normalized_key=normalized_key,
        description=None,
        url=canonicalize_url(url) if url else None,
        source_signal_ids=[source_signal_id],
        confidence=Confidence(
            value=confidence,
            factors=[],
            reason="deterministic extraction rule",
            evidence_count=1,
        ),
        metadata=metadata or {"extraction_method": "deterministic_rule"},
    )
