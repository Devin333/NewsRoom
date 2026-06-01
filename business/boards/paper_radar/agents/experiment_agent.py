"""Experiment and benchmark extraction agent for paper radar analysis."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from framework.agent.session import AgentSessionItem

from business.boards.paper_radar.agents.models import PaperAgentContext, PaperAgentResult
from business.boards.paper_radar.agents.roles import PAPER_ROLE_EXPERIMENT_RESULT, PAPER_ROLE_TAXONOMY_RESULT


BENCHMARK_ALIASES: Mapping[str, tuple[str, str]] = {
    "swe-bench": ("SWE-bench", "software-engineering"),
    "humaneval": ("HumanEval", "code-generation"),
    "mbpp": ("MBPP", "code-generation"),
    "gsm8k": ("GSM8K", "reasoning-math"),
    "mmlu": ("MMLU", "language-understanding"),
    "imagenet": ("ImageNet", "image-classification"),
    "squad": ("SQuAD", "question-answering"),
    "vqa": ("VQA", "visual-question-answering"),
}

METRIC_PATTERN = re.compile(
    r"(?P<metric>accuracy|f1|bleu|rouge|pass@1|resolved|success rate|exact match|em|score|wer|latency|perplexity)"
    r"\s*(?:of|=|:|is|was|are|reaches|reached|achieves|achieved|reports?|at|to)?\s*"
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>%|percent|points?)?",
    flags=re.IGNORECASE,
)
VALUE_FIRST_PATTERN = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>%|percent|points?)?\s*"
    r"(?P<metric>accuracy|f1|bleu|rouge|pass@1|resolved|success rate|exact match|em|score|wer)",
    flags=re.IGNORECASE,
)
RESULT_HINTS = ("benchmark", "dataset", "evaluation", "experiment", "result", "accuracy", "f1", "bleu", "swe-bench", "mmlu", "humaneval")


class PaperExperimentAgent:
    """Extract benchmark candidates, metrics, and comparison evidence."""

    agent_id = "paper-experiment-agent"

    def run(self, context: PaperAgentContext) -> PaperAgentResult:
        taxonomy = _latest_output(context.shared_items, PAPER_ROLE_TAXONOMY_RESULT)
        sentences = _candidate_sentences(context.request.abstract, context.request.page_sections)
        benchmarks = _extract_benchmarks(sentences, taxonomy)
        warnings = [] if benchmarks else ["No concrete benchmark metric value was extracted."]
        summary = _experiment_summary(benchmarks, sentences)
        output = {
            "benchmarks": benchmarks,
            "experimentSummary": summary,
            "metricWarnings": warnings,
        }
        return PaperAgentResult(
            agent_id=self.agent_id,
            role=PAPER_ROLE_EXPERIMENT_RESULT,
            output=output,
            summary=summary,
            confidence=0.82 if benchmarks else 0.45,
        )


def _extract_benchmarks(sentences: Sequence[str], taxonomy: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    results: list[Mapping[str, Any]] = []
    for sentence in sentences:
        benchmark_name, category = _benchmark_from_sentence(sentence, taxonomy)
        metric = _metric_from_sentence(sentence)
        if benchmark_name is None and not metric:
            continue
        if benchmark_name is None:
            benchmark_name = "Reported benchmark"
            category = _category_from_taxonomy(taxonomy)
        if not metric:
            continue
        value = metric["value"]
        slug = _slugify(benchmark_name)
        results.append(
            {
                "id": f"bench-{slug}",
                "name": benchmark_name,
                "category": category,
                "taskSlug": _task_slug(taxonomy),
                "metric": metric["metric"],
                "value": value,
                "unit": metric.get("unit"),
                "baseline": _baseline_from_sentence(sentence),
                "higherIsBetter": _higher_is_better(metric["metric"]),
                "evidence": sentence[:500],
                "confidence": 0.86,
            }
        )
    return _dedupe_benchmarks(results)


def _candidate_sentences(abstract: str, page_sections: Sequence[Mapping[str, Any]]) -> list[str]:
    text_parts = [abstract]
    for section in page_sections:
        section_text = " ".join(
            [
                str(section.get("title") or ""),
                str(section.get("sectionType") or ""),
                str(section.get("textExcerpt") or ""),
            ]
        )
        if any(hint in section_text.casefold() for hint in RESULT_HINTS):
            text_parts.append(section_text)
    text = "\n".join(text_parts)
    candidates = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        clean = " ".join(sentence.split())
        if clean and any(hint in clean.casefold() for hint in RESULT_HINTS):
            candidates.append(clean)
    return candidates[:24]


def _benchmark_from_sentence(sentence: str, taxonomy: Mapping[str, Any]) -> tuple[str | None, str]:
    lowered = sentence.casefold()
    for alias, (name, category) in BENCHMARK_ALIASES.items():
        if alias in lowered:
            return name, category
    for category in _sequence(taxonomy.get("benchmarkCategories")):
        text = str(category)
        if text and text.replace("-", " ") in lowered:
            return _title_from_slug(text), text
    return None, _category_from_taxonomy(taxonomy)


def _metric_from_sentence(sentence: str) -> Mapping[str, Any] | None:
    match = VALUE_FIRST_PATTERN.search(sentence) or METRIC_PATTERN.search(sentence)
    if not match:
        return None
    unit = match.group("unit")
    value = float(match.group("value"))
    if value.is_integer():
        value = int(value)
    return {
        "metric": _normalize_metric(match.group("metric")),
        "value": value,
        "unit": "%" if unit and unit.casefold() in {"%", "percent"} else unit,
    }


def _baseline_from_sentence(sentence: str) -> str | None:
    match = re.search(r"\b(?:than|over|vs\.?|versus|compared with)\s+([A-Za-z0-9_.+\- ]{2,40})", sentence, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip(" .,:;")


def _higher_is_better(metric: str) -> bool:
    return metric.casefold() not in {"latency", "perplexity", "wer", "error rate"}


def _experiment_summary(benchmarks: Sequence[Mapping[str, Any]], sentences: Sequence[str]) -> str:
    if benchmarks:
        names = ", ".join(str(item.get("name")) for item in benchmarks[:3])
        return f"Extracted {len(benchmarks)} benchmark result(s): {names}."
    if sentences:
        return "Experiment-related sections were found, but no concrete benchmark metric value was extracted."
    return "No explicit experiment or benchmark evidence was found in the abstract or section excerpts."


def _latest_output(items: Sequence[AgentSessionItem], role: str) -> Mapping[str, Any]:
    for item in reversed(items):
        if item.role == role:
            return item.content
    return {}


def _category_from_taxonomy(taxonomy: Mapping[str, Any]) -> str:
    categories = _sequence(taxonomy.get("benchmarkCategories"))
    if categories:
        return str(categories[0])
    primary = str(taxonomy.get("primaryTaskGroup") or "")
    if primary == "code-ai":
        return "code-generation"
    if primary == "computer-vision":
        return "image-classification"
    if primary == "reasoning":
        return "reasoning-math"
    return "data-quality-evaluation"


def _task_slug(taxonomy: Mapping[str, Any]) -> str | None:
    task_refs = _sequence(taxonomy.get("taskRefs"))
    if task_refs and isinstance(task_refs[0], Mapping):
        return str(task_refs[0].get("slug") or "") or None
    return str(taxonomy.get("primaryTaskGroup") or "") or None


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []


def _dedupe_benchmarks(items: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    result: list[Mapping[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        key = (str(item.get("name") or ""), str(item.get("metric") or ""))
        if key in seen:
            continue
        seen.add(key)
        result.append({key: value for key, value in item.items() if value not in (None, "", [], {})})
    return result


def _normalize_metric(value: str) -> str:
    return value.strip().lower().replace("em", "exact match")


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _title_from_slug(value: str) -> str:
    return " ".join(part.upper() if part == "ai" else part.capitalize() for part in value.split("-"))
