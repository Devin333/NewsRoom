from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


FIXED_NOW = datetime(2026, 5, 29, 8, 0, tzinfo=UTC)
FIXED_NOW_ISO = "2026-05-29T08:00:00Z"


def project_dataset_payload() -> dict[str, Any]:
    return {
        "source": "backend",
        "source_run_id": "projects-prd-fixture-2026-05-29",
        "generated_at": FIXED_NOW_ISO,
        "notices": ["fixture uses public project metadata only"],
        "projects": [
            {
                "id": "project-langfuse",
                "name": "Langfuse",
                "slug": "langfuse",
                "tagline": "Open source LLM engineering platform",
                "description": "LLM observability, prompt management, and evaluation workflows.",
                "canonical_url": "https://langfuse.com/",
                "website_url": "https://langfuse.com/",
                "github_url": "https://github.com/langfuse/langfuse",
                "docs_url": "https://langfuse.com/docs",
                "project_type": "tool",
                "category": "llm-observability",
                "tags": ["llmops", "observability", "tracing", "evals"],
                "status": "active",
                "source_confidence": 0.95,
                "suitable_for": ["product engineers", "ai platform teams"],
                "learnable_points": ["trace-first UX", "prompt and eval workflow bridging"],
            },
            {
                "id": "project-open-webui",
                "name": "Open WebUI",
                "slug": "open-webui",
                "tagline": "Self-hosted AI interface",
                "description": "A self-hosted AI chat interface with model and tool integrations.",
                "canonical_url": "https://openwebui.com/",
                "website_url": "https://openwebui.com/",
                "github_url": "https://github.com/open-webui/open-webui",
                "docs_url": "https://docs.openwebui.com/",
                "project_type": "product",
                "category": "ai-workspace",
                "tags": ["self-hosted", "chat-ui", "local-ai"],
                "status": "active",
                "source_confidence": 0.78,
                "suitable_for": ["internal tool teams"],
                "learnable_points": ["model routing UX", "plugin and tool management"],
            },
            {
                "id": "project-missing-public-metrics",
                "name": "Internal Evaluation Dashboard",
                "slug": "internal-evaluation-dashboard",
                "tagline": "Private case used to verify absence of fabricated public metrics",
                "description": "A private dashboard entry with no public GitHub or launch metrics.",
                "canonical_url": "https://example.invalid/internal-eval-dashboard",
                "project_type": "project",
                "category": "evaluation",
                "tags": ["evaluation"],
                "status": "active",
                "source_confidence": 0.62,
            },
        ],
        "sources": [
            {
                "id": "src-langfuse-github",
                "project_id": "project-langfuse",
                "source_name": "GitHub",
                "source_type": "github",
                "source_url": "https://github.com/langfuse/langfuse",
                "external_id": "langfuse/langfuse",
                "raw_title": "langfuse/langfuse",
                "raw_description": "Open source LLM engineering platform.",
                "raw_metadata": {"authorization": "Bearer secret-token"},
                "fetched_at": FIXED_NOW_ISO,
            },
            {
                "id": "src-langfuse-docs",
                "project_id": "project-langfuse",
                "source_name": "Official Docs",
                "source_type": "official_blog",
                "source_url": "https://langfuse.com/docs",
                "raw_title": "Langfuse Docs",
                "raw_description": "Documentation for traces, prompts, and evaluations.",
                "fetched_at": FIXED_NOW_ISO,
            },
            {
                "id": "src-open-webui-github",
                "project_id": "project-open-webui",
                "source_name": "GitHub",
                "source_type": "github",
                "source_url": "https://github.com/open-webui/open-webui",
                "external_id": "open-webui/open-webui",
                "fetched_at": FIXED_NOW_ISO,
            },
        ],
        "metric_snapshots": [
            {
                "id": "metrics-langfuse-2026-05-29",
                "project_id": "project-langfuse",
                "snapshot_at": FIXED_NOW_ISO,
                "github_stars": 12000,
                "github_forks": 900,
                "internal_views": 42,
                "internal_saves": 8,
                "internal_watches": 5,
                "internal_lab_uses": 3,
                "source_mentions": 7,
                "release_count": 3,
                "quality_score": 0.92,
                "activity_score": 0.87,
                "evidence_score": 0.95,
            },
            {
                "id": "metrics-open-webui-2026-05-29",
                "project_id": "project-open-webui",
                "snapshot_at": FIXED_NOW_ISO,
                "github_stars": 102000,
                "internal_views": 24,
                "internal_saves": 2,
                "source_mentions": 1,
                "release_count": 0,
                "quality_score": 0.72,
                "activity_score": 0.52,
                "evidence_score": 0.44,
            },
            {
                "id": "metrics-private-2026-05-29",
                "project_id": "project-missing-public-metrics",
                "snapshot_at": FIXED_NOW_ISO,
                "internal_views": 4,
                "internal_saves": 1,
                "source_mentions": 1,
            },
        ],
        "growth_snapshots": [
            {
                "id": "growth-langfuse-7d",
                "project_id": "project-langfuse",
                "window": "7d",
                "stars_start": 11160,
                "stars_end": 12000,
                "stars_delta": 840,
                "mentions_delta": 6,
                "internal_watch_delta": 4,
                "release_count": 3,
                "computed_at": FIXED_NOW_ISO,
            },
            {
                "id": "growth-open-webui-7d",
                "project_id": "project-open-webui",
                "window": "7d",
                "stars_start": 101988,
                "stars_end": 102000,
                "stars_delta": 12,
                "mentions_delta": 1,
                "internal_watch_delta": 0,
                "release_count": 0,
                "computed_at": FIXED_NOW_ISO,
            },
        ],
        "capabilities": [
            {
                "id": "cap-langfuse-tracing",
                "project_id": "project-langfuse",
                "name": "LLM Trace Capture",
                "capability_type": "observability",
                "description": "Capture prompts, generations, spans, and evaluation metadata.",
                "reusable_level": "high",
                "difficulty": "medium",
                "target_modules": ["agent-runtime", "quality-gate"],
            }
        ],
        "tool_profiles": [
            {
                "project_id": "project-langfuse",
                "tool_type": "llm-observability",
                "input_types": ["trace", "prompt", "generation"],
                "output_types": ["dashboard", "metrics", "eval-result"],
                "is_open_source": True,
                "license": "MIT",
                "local_deployable": True,
                "has_api": True,
                "has_python_sdk": True,
                "has_docker": True,
                "integration_difficulty": "medium",
                "recommended_integration": "wrap_as_service",
                "target_modules": ["agent-runtime", "evaluation"],
                "setup_commands": ["docker compose up"],
                "known_limits": ["requires explicit secret configuration"],
                "experiment_status": "runnable",
            }
        ],
        "cases": [
            {
                "id": "case-langfuse-tracing",
                "project_id": "project-langfuse",
                "title": "Trace-first LLM workflow",
                "business_domain": "ai-platform",
                "module_type": "observability",
                "problem": "Teams need to debug agent runs using public evidence and internal traces.",
                "design_summary": "Bridge trace collection into evaluation and review workflows.",
                "plain_explanation": "Capture each model interaction as a trace and attach review signals.",
                "design_logic": "Trace data becomes evidence for ranking, review, and quality gates.",
                "components": [
                    {
                        "id": "component-trace-ingestor",
                        "case_id": "case-langfuse-tracing",
                        "name": "Trace Ingestor",
                        "component_type": "adapter",
                        "responsibility": "Convert runtime spans into project evidence.",
                        "plain_explanation": "An adapter receives traces and stores only review-safe fields.",
                    }
                ],
                "patterns": [
                    {
                        "id": "pattern-evidence-bridge",
                        "case_id": "case-langfuse-tracing",
                        "name": "Evidence Bridge",
                        "pattern_type": "integration",
                        "explanation": "Translate tool-specific traces into stable business evidence.",
                        "when_to_use": "Use when public metadata must connect to internal review state.",
                        "pros": ["Keeps UI and service contracts stable"],
                        "cons": ["Needs strict redaction boundaries"],
                    }
                ],
                "data_flow": [
                    {
                        "id": "flow-trace-to-ranking",
                        "case_id": "case-langfuse-tracing",
                        "order": 1,
                        "title": "Trace to ranking feature",
                        "description": "Trace evidence updates quality and activity ranking features.",
                    }
                ],
                "migration_level": "high",
                "reference_value": "high",
                "difficulty": "medium",
                "suitable_for": ["observability backlog"],
                "source_refs": ["src-langfuse-github", "src-langfuse-docs"],
                "status": "published",
            }
        ],
        "collections": [
            {
                "id": "collection-observability",
                "slug": "llm-observability-stack",
                "title": "LLM Observability Stack",
                "description": "Projects useful for tracing and evaluating LLM products.",
                "collection_type": "toolset",
                "tags": ["observability", "evals"],
                "target_audience": ["ai platform teams"],
                "learning_goals": ["Understand trace-to-eval workflows"],
                "item_count": 1,
                "status": "published",
            }
        ],
    }


def write_project_dataset(path: Path) -> Path:
    path.write_text(json.dumps(project_dataset_payload(), indent=2), encoding="utf-8")
    return path


def as_plain(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return as_plain(value.to_dict())
    if hasattr(value, "model_dump"):
        return as_plain(value.model_dump(mode="json", exclude_none=True))
    if hasattr(value, "dict"):
        return as_plain(value.dict())
    if isinstance(value, dict):
        return {str(key): as_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [as_plain(item) for item in value]
    return value


def get_value(payload: Any, *names: str) -> Any:
    plain = as_plain(payload)
    if isinstance(plain, dict):
        for name in names:
            if name in plain:
                return plain[name]
    for name in names:
        if hasattr(payload, name):
            return getattr(payload, name)
    raise AssertionError(f"missing any of fields: {', '.join(names)}")


def get_optional(payload: Any, *names: str) -> Any:
    plain = as_plain(payload)
    if isinstance(plain, dict):
        for name in names:
            if name in plain:
                return plain[name]
    for name in names:
        if hasattr(payload, name):
            return getattr(payload, name)
    return None


def project_items(result: Any) -> list[Any]:
    payload = as_plain(result)
    items = get_optional(payload, "projects", "items", "results")
    assert isinstance(items, list)
    return items


def assert_public_payload(payload: Any) -> None:
    serialized = json.dumps(as_plain(payload), sort_keys=True)
    assert "raw_payload" not in serialized
    assert "rawMetadata" not in serialized
    assert "raw_metadata" not in serialized
    assert "authorization" not in serialized
    assert "secret-token" not in serialized
    assert "Bearer" not in serialized
