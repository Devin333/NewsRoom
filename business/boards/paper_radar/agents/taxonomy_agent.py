"""Taxonomy classification agent for paper radar analysis."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from business.boards.paper_radar.agents.models import PaperAgentContext, PaperAgentResult
from business.boards.paper_radar.agents.roles import PAPER_ROLE_SEMANTIC_SECTIONS, PAPER_ROLE_TAXONOMY_RESULT
from business.boards.paper_radar.taxonomy_categories import (
    AI_TASK_GROUPS,
    BENCHMARK_CATEGORIES,
    load_pwc_method_collections,
    normalize_ai_task_group,
    normalize_benchmark_category,
    normalize_method_collection,
)


TASK_GROUP_TERMS: Mapping[str, tuple[str, ...]] = {
    "agents": ("agent", "multi-agent", "tool use", "planner", "autonomous"),
    "language-models": ("language model", "llm", "transformer", "prompt", "gpt"),
    "reasoning": ("reasoning", "chain-of-thought", "math", "gsm8k", "logic"),
    "multimodal": ("multimodal", "vision-language", "image-text", "vqa"),
    "computer-vision": ("computer vision", "image", "imagenet", "detection", "segmentation"),
    "speech-audio": ("speech", "audio", "asr", "tts", "sound"),
    "code-ai": ("code", "programming", "humaneval", "mbpp", "swe-bench", "software engineering"),
    "robotics-embodied": ("robot", "robotics", "embodied", "manipulation", "navigation"),
    "retrieval-knowledge": ("retrieval", "rag", "knowledge graph", "search", "grounding"),
    "data-evaluation": ("benchmark", "evaluation", "dataset", "data quality", "annotation"),
    "systems-infra": ("inference", "serving", "latency", "throughput", "systems"),
    "security-safety": ("safety", "alignment", "robustness", "privacy", "jailbreak"),
    "ai-for-science": ("science", "biology", "protein", "molecule", "chemistry", "medical"),
    "human-ai-interaction": ("human-ai", "user study", "interface", "interaction"),
}

METHOD_TERMS: Mapping[str, tuple[str, ...]] = {
    "Transformers": ("transformer", "attention", "self-attention"),
    "Attention Mechanisms": ("attention", "cross-attention"),
    "Language Models": ("language model", "llm", "gpt", "prompt"),
    "Diffusion Models": ("diffusion", "denoising"),
    "Object Detection Models": ("object detection", "detector", "detection"),
    "Convolutional Neural Networks": ("cnn", "convolutional"),
    "Graph Models": ("graph neural", "gnn", "knowledge graph"),
    "Reinforcement Learning": ("reinforcement learning", "rl", "policy optimization"),
    "Representation Learning": ("representation learning", "embedding"),
    "Optimization": ("optimization", "optimizer", "gradient"),
}

BENCHMARK_TERMS: Mapping[str, tuple[str, ...]] = {
    "software-engineering": ("swe-bench", "software engineering"),
    "code-generation": ("humaneval", "mbpp", "code generation"),
    "reasoning-math": ("gsm8k", "math", "mmlu math"),
    "language-understanding": ("mmlu", "glue", "superglue"),
    "question-answering": ("question answering", "qa", "squad"),
    "image-classification": ("imagenet", "image classification"),
    "visual-question-answering": ("vqa", "visual question answering"),
    "agent-task-completion": ("agent task", "task completion"),
    "tool-use": ("tool use", "function calling"),
}


class PaperTaxonomyAgent:
    """Classify paper task groups, methods, and benchmark categories."""

    agent_id = "paper-taxonomy-agent"
    required_roles = (PAPER_ROLE_SEMANTIC_SECTIONS,)
    produced_role = PAPER_ROLE_TAXONOMY_RESULT

    def run(self, context: PaperAgentContext) -> PaperAgentResult:
        text = _analysis_text(context.request.title, context.request.abstract, context.request.page_sections)
        task_scores = _score_terms(text, TASK_GROUP_TERMS)
        ranked_groups = [group for group, score in sorted(task_scores.items(), key=lambda item: item[1], reverse=True) if score > 0]
        primary = normalize_ai_task_group(ranked_groups[0]) if ranked_groups else None
        secondary = [group for group in ranked_groups[1:3] if normalize_ai_task_group(group)]
        confidence = _taxonomy_confidence(task_scores.get(primary or "", 0), bool(primary))
        benchmark_categories = _benchmark_categories(text, primary)
        task_refs = [_task_ref(group, confidence, text) for group in ([primary] if primary else []) + secondary]
        method_refs = _method_refs(text, confidence)
        evidence_summary = _evidence_summary(primary, method_refs, benchmark_categories)
        output = {
            "primaryTaskGroup": primary,
            "secondaryTaskGroups": secondary,
            "taskRefs": task_refs,
            "methodRefs": method_refs,
            "benchmarkCategories": benchmark_categories,
            "confidence": confidence,
            "evidenceSummary": evidence_summary,
        }
        return PaperAgentResult(
            agent_id=self.agent_id,
            role=PAPER_ROLE_TAXONOMY_RESULT,
            output=output,
            summary=evidence_summary,
            confidence=confidence,
        )


def _analysis_text(title: str, abstract: str, page_sections: Sequence[Mapping[str, Any]]) -> str:
    parts = [title, abstract]
    for section in page_sections[:12]:
        parts.extend(
            [
                str(section.get("title") or ""),
                str(section.get("sectionType") or ""),
                str(section.get("textExcerpt") or "")[:2000],
            ]
        )
    return "\n".join(part for part in parts if part).casefold()


def _score_terms(text: str, terms_by_key: Mapping[str, Sequence[str]]) -> dict[str, int]:
    scores: dict[str, int] = {}
    for key, terms in terms_by_key.items():
        scores[key] = sum(_count_term(text, term) for term in terms)
    return scores


def _count_term(text: str, term: str) -> int:
    return len(re.findall(rf"(?<![a-z0-9]){re.escape(term.casefold())}(?![a-z0-9])", text))


def _taxonomy_confidence(score: int, has_primary: bool) -> float:
    if not has_primary:
        return 0.25
    return round(min(0.92, 0.58 + score * 0.08), 2)


def _task_ref(group: str | None, confidence: float, text: str) -> Mapping[str, Any]:
    group_slug = normalize_ai_task_group(group)
    if not group_slug:
        return {}
    return {
        "id": f"task-{group_slug}",
        "slug": group_slug,
        "name": _title_from_slug(group_slug),
        "group": group_slug,
        "confidence": confidence,
        "evidence": _evidence_for_terms(text, TASK_GROUP_TERMS.get(group_slug, ())),
    }


def _method_refs(text: str, confidence: float) -> list[Mapping[str, Any]]:
    collections = load_pwc_method_collections()
    refs: list[Mapping[str, Any]] = []
    for collection, terms in METHOD_TERMS.items():
        normalized = normalize_method_collection(collection, collections=collections)
        if not normalized or not any(term.casefold() in text for term in terms):
            continue
        refs.append(
            {
                "id": f"method-{_slugify(normalized)}",
                "slug": _slugify(normalized),
                "name": normalized,
                "area": normalized,
                "confidence": confidence,
                "evidence": _evidence_for_terms(text, terms),
            }
        )
    if not refs and "language model" in text:
        normalized = normalize_method_collection("Language Models", collections=collections)
        if normalized:
            refs.append(
                {
                    "id": "method-language-models",
                    "slug": "language-models",
                    "name": normalized,
                    "area": normalized,
                    "confidence": max(0.55, confidence - 0.1),
                    "evidence": "The paper discusses language models.",
                }
            )
    return _dedupe_refs(refs)


def _benchmark_categories(text: str, primary_group: str | None) -> list[str]:
    categories = []
    for category, terms in BENCHMARK_TERMS.items():
        normalized = normalize_benchmark_category(category)
        if normalized and any(term.casefold() in text for term in terms):
            categories.append(normalized)
    for category in BENCHMARK_CATEGORIES:
        if category.replace("-", " ") in text:
            categories.append(category)
    if not categories and primary_group == "code-ai":
        categories.append("code-generation")
    return list(dict.fromkeys(categories))


def _evidence_summary(primary: str | None, method_refs: Sequence[Mapping[str, Any]], benchmark_categories: Sequence[str]) -> str:
    if not primary:
        return "No confident task group could be inferred from the title, abstract, or section excerpts."
    methods = ", ".join(str(item.get("name")) for item in method_refs[:2]) or "no specific method collection"
    benchmarks = ", ".join(benchmark_categories[:2]) or "no explicit benchmark category"
    return f"Classified as {_title_from_slug(primary)} with {methods} and {benchmarks} evidence."


def _evidence_for_terms(text: str, terms: Sequence[str]) -> str:
    matched = [term for term in terms if term.casefold() in text]
    return f"Matched terms: {', '.join(matched[:3])}." if matched else "Matched taxonomy context."


def _dedupe_refs(refs: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    result: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        slug = str(ref.get("slug") or "")
        if not slug or slug in seen:
            continue
        seen.add(slug)
        result.append(ref)
    return result


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _title_from_slug(value: str) -> str:
    return " ".join(part.upper() if part == "ai" else part.capitalize() for part in value.split("-"))
