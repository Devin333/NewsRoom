from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from business.foundation import (
    AnalysisContext,
    Claim,
    ClaimModality,
    ClaimPolarity,
    ClaimType,
    Confidence,
    Entity,
    EntityType,
    ObjectRef,
    ObjectType,
    Signal,
    TaxonomyType,
    Technology,
    TechnologyCategory,
    Topic,
    build_stable_id,
    canonicalize_url,
    normalize_key,
)
from business.layers.extraction.models import ExtractionResult, ExtractionWarning, TaxonomyAssignment


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


class ExtractionPipeline:
    def run(self, signals: list[Signal], context: AnalysisContext) -> list[ExtractionResult]:
        return [self.extract(signal, context) for signal in signals]

    def extract(self, signal: Signal, context: AnalysisContext) -> ExtractionResult:
        entities = self._extract_entities(signal)
        topics = self._extract_topics(signal)
        technologies = self._extract_technologies(signal)
        claims = self._extract_claims(signal, entities, topics, technologies)
        assignments = self._classify(signal, topics, technologies)
        return ExtractionResult(
            signal_id=signal.signal_id,
            entities=entities,
            topics=topics,
            technologies=technologies,
            claims=claims,
            taxonomy_assignments=assignments,
            warnings=[],
            metadata={
                "board_type": signal.board_type.value,
                "signal_type": signal.signal_type.value,
                "taxonomy_version": context.taxonomy_version,
            },
        )

    def _extract_entities(self, signal: Signal) -> list[Entity]:
        text = _signal_text(signal)
        entities: list[Entity] = []
        if signal.signal_type.value == "github_project":
            repo = _github_repo_from_signal(signal)
            if repo:
                entities.append(
                    self._build_entity(
                        entity_type=EntityType.GITHUB_PROJECT,
                        canonical_name=repo,
                        source_signal_id=signal.signal_id,
                        url=signal.url,
                        aliases=[signal.source.source_name, signal.title],
                        confidence=0.95,
                    )
                )
        if signal.signal_type.value == "paper":
            paper_id = _paper_id_from_signal(signal)
            if paper_id:
                entities.append(
                    self._build_entity(
                        entity_type=EntityType.PAPER,
                        canonical_name=paper_id,
                        source_signal_id=signal.signal_id,
                        url=signal.url,
                        aliases=[signal.title],
                        confidence=0.95,
                    )
                )
        if signal.signal_type.value == "ai_news":
            for hint in COMPANY_HINTS:
                if hint in text:
                    entities.append(
                        self._build_entity(
                            entity_type=EntityType.COMPANY,
                            canonical_name=hint,
                            source_signal_id=signal.signal_id,
                            confidence=0.75,
                        )
                    )
        if signal.signal_type.value == "community_discussion":
            for hint in COMPANY_HINTS | KNOWN_MODEL_HINTS:
                if hint in text:
                    entities.append(
                        self._build_entity(
                            entity_type=EntityType.UNKNOWN,
                            canonical_name=hint,
                            source_signal_id=signal.signal_id,
                            confidence=0.55,
                        )
                    )
        return _dedupe_by_key(entities, key=lambda item: item.normalized_key)

    def _extract_topics(self, signal: Signal) -> list[Topic]:
        text = _signal_text(signal)
        candidates: list[Topic] = []
        for keyword, normalized in TOPIC_KEYWORDS.items():
            if keyword in text:
                candidates.append(
                    Topic(
                        topic_id=build_stable_id("topic", normalized),
                        name=normalized.title() if normalized != "llmops" else "LLMOps",
                        normalized_key=normalize_key(normalized),
                        aliases=[keyword],
                        keywords=[keyword],
                        description=None,
                        confidence=Confidence(value=0.82, factors=[]),
                    )
                )
        if not candidates:
            candidates.append(
                Topic(
                    topic_id=build_stable_id("topic", "unknown topic", signal.signal_id),
                    name="Unknown Topic",
                    normalized_key="unknown_topic",
                    aliases=[],
                    keywords=[],
                    description="Fallback topic",
                    confidence=Confidence(value=0.35, factors=[]),
                )
            )
        return _dedupe_by_key(candidates, key=lambda item: item.normalized_key)

    def _extract_technologies(self, signal: Signal) -> list[Technology]:
        text = _signal_text(signal)
        candidates: list[Technology] = []
        for keyword, (category, normalized) in TECH_KEYWORD_MAP.items():
            if keyword in text:
                candidates.append(
                    Technology(
                        technology_id=build_stable_id("tech", normalized),
                        name=_titleize_technology(normalized),
                        normalized_key=normalize_key(normalized),
                        category=category,
                        aliases=[keyword],
                        keywords=[keyword],
                        description=None,
                        first_seen_signal_id=signal.signal_id,
                        confidence=Confidence(value=0.84, factors=[]),
                    )
                )
        if signal.signal_type.value == "paper" and not candidates:
            title_text = signal.title.casefold()
            for keyword, (category, normalized) in TECH_KEYWORD_MAP.items():
                if keyword in title_text:
                    candidates.append(
                        Technology(
                            technology_id=build_stable_id("tech", normalized, signal.signal_id),
                            name=_titleize_technology(normalized),
                            normalized_key=normalize_key(normalized),
                            category=category,
                            aliases=[keyword],
                            keywords=[keyword],
                            description=None,
                            first_seen_signal_id=signal.signal_id,
                            confidence=Confidence(value=0.72, factors=[]),
                        )
                    )
        return _dedupe_by_key(candidates, key=lambda item: item.normalized_key)

    def _extract_claims(
        self,
        signal: Signal,
        entities: list[Entity],
        topics: list[Topic],
        technologies: list[Technology],
    ) -> list[Claim]:
        text = signal.title if signal.summary is None else f"{signal.title} {signal.summary}"
        lowered = text.casefold()
        claims: list[Claim] = []
        for technology in technologies:
            if signal.signal_type.value == "paper":
                claims.append(
                    Claim(
                        claim_id=build_stable_id("claim", signal.signal_id, technology.technology_id, "proposes"),
                        signal_id=signal.signal_id,
                        claim_type=ClaimType.TECHNICAL_METHOD,
                        text=f"{signal.title} proposes {technology.name}",
                        subject_ref=ObjectRef(object_type="paper", object_id=signal.signal_id, label=signal.title),
                        predicate="proposes",
                        object_ref=ObjectRef(object_type="technology", object_id=technology.technology_id, label=technology.name),
                        polarity=ClaimPolarity.NEUTRAL,
                        modality=ClaimModality.REPORTED,
                        confidence=Confidence(value=0.78, factors=[]),
                    )
                )
            elif signal.signal_type.value == "github_project":
                claims.append(
                    Claim(
                        claim_id=build_stable_id("claim", signal.signal_id, technology.technology_id, "implements"),
                        signal_id=signal.signal_id,
                        claim_type=ClaimType.IMPLEMENTATION_CLAIM,
                        text=f"{signal.title} implements {technology.name}",
                        subject_ref=ObjectRef(object_type="project", object_id=signal.signal_id, label=signal.title),
                        predicate="implements",
                        object_ref=ObjectRef(object_type="technology", object_id=technology.technology_id, label=technology.name),
                        polarity=ClaimPolarity.POSITIVE,
                        modality=ClaimModality.ASSERTED,
                        confidence=Confidence(value=0.76, factors=[]),
                    )
                )
            elif signal.signal_type.value == "community_discussion":
                claims.append(
                    Claim(
                        claim_id=build_stable_id("claim", signal.signal_id, technology.technology_id, "community"),
                        signal_id=signal.signal_id,
                        claim_type=ClaimType.COMMUNITY_FEEDBACK,
                        text=f"Community discusses {technology.name}",
                        subject_ref=ObjectRef(object_type="community_thread", object_id=signal.signal_id, label=signal.title),
                        predicate="discusses",
                        object_ref=ObjectRef(object_type="technology", object_id=technology.technology_id, label=technology.name),
                        polarity=ClaimPolarity.MIXED,
                        modality=ClaimModality.REPORTED,
                        confidence=Confidence(value=0.66, factors=[]),
                    )
                )
            elif signal.signal_type.value == "ai_news":
                claims.append(
                    Claim(
                        claim_id=build_stable_id("claim", signal.signal_id, technology.technology_id, "adopts"),
                        signal_id=signal.signal_id,
                        claim_type=ClaimType.ADOPTION_CLAIM,
                        text=f"{signal.title} adopts {technology.name}",
                        subject_ref=ObjectRef(object_type="news_item", object_id=signal.signal_id, label=signal.title),
                        predicate="adopts",
                        object_ref=ObjectRef(object_type="technology", object_id=technology.technology_id, label=technology.name),
                        polarity=ClaimPolarity.POSITIVE,
                        modality=ClaimModality.REPORTED,
                        confidence=Confidence(value=0.72, factors=[]),
                    )
                )
        if signal.signal_type.value == "community_discussion" and not claims:
            claims.append(
                Claim(
                    claim_id=build_stable_id("claim", signal.signal_id, "community", "feedback"),
                    signal_id=signal.signal_id,
                    claim_type=ClaimType.COMMUNITY_FEEDBACK,
                    text=signal.summary or signal.title,
                    subject_ref=None,
                    predicate=None,
                    object_ref=None,
                    polarity=ClaimPolarity.NEUTRAL,
                    modality=ClaimModality.REPORTED,
                    confidence=Confidence(value=0.52, factors=[]),
                )
            )
        if signal.signal_type.value == "paper" and not claims:
            claims.append(
                Claim(
                    claim_id=build_stable_id("claim", signal.signal_id, "paper", "technical_method"),
                    signal_id=signal.signal_id,
                    claim_type=ClaimType.TECHNICAL_METHOD,
                    text=signal.summary or signal.title,
                    subject_ref=ObjectRef(object_type="paper", object_id=signal.signal_id, label=signal.title),
                    predicate="proposes",
                    object_ref=None,
                    polarity=ClaimPolarity.NEUTRAL,
                    modality=ClaimModality.REPORTED,
                    confidence=Confidence(value=0.55, factors=[]),
                )
            )
        return claims

    def _classify(
        self,
        signal: Signal,
        topics: list[Topic],
        technologies: list[Technology],
    ) -> list[TaxonomyAssignment]:
        assignments: list[TaxonomyAssignment] = []
        for topic in topics:
            assignments.append(
                TaxonomyAssignment(
                    object_ref=ObjectRef(object_type="topic", object_id=topic.topic_id, label=topic.name),
                    taxonomy_type=TaxonomyType.TOPIC,
                    category=topic.normalized_key,
                    confidence=Confidence(value=topic.confidence.value, factors=list(topic.confidence.factors)),
                    evidence_text=signal.title,
                )
            )
        for technology in technologies:
            assignments.append(
                TaxonomyAssignment(
                    object_ref=ObjectRef(object_type="technology", object_id=technology.technology_id, label=technology.name),
                    taxonomy_type=TaxonomyType.TECHNOLOGY,
                    category=technology.category.value,
                    subcategory=technology.subcategory,
                    confidence=Confidence(value=technology.confidence.value, factors=list(technology.confidence.factors)),
                    evidence_text=signal.summary or signal.title,
                )
            )
        return assignments

    def _build_entity(
        self,
        *,
        entity_type: EntityType,
        canonical_name: str,
        source_signal_id: str,
        confidence: float,
        url: str | None = None,
        aliases: list[str] | None = None,
    ) -> Entity:
        normalized_key = normalize_key(canonical_name)
        return Entity(
            entity_id=build_stable_id("entity", entity_type.value, normalized_key),
            entity_type=entity_type,
            canonical_name=_canonical_name(canonical_name),
            aliases=_clean_strings(aliases or []),
            normalized_key=normalized_key,
            description=None,
            url=canonicalize_url(url) if url else None,
            source_signal_ids=[source_signal_id],
            confidence=Confidence(value=confidence, factors=[]),
            metadata={},
        )


def _signal_text(signal: Signal) -> str:
    parts = [signal.title, signal.summary or "", signal.content or "", " ".join(signal.tags), " ".join(signal.authors)]
    return " ".join(part for part in parts if part).casefold()


def _github_repo_from_signal(signal: Signal) -> str | None:
    url = signal.url or signal.source.source_url or ""
    path = urlsplit(url).path.strip("/")
    parts = path.split("/")
    if len(parts) >= 2:
        owner, repo = parts[0], parts[1]
        if owner and repo:
            return f"{owner.casefold()}/{repo.casefold()}"
    title = signal.title.strip()
    match = re.search(r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", title)
    if match:
        return f"{match.group(1).casefold()}/{match.group(2).casefold()}"
    return None


def _paper_id_from_signal(signal: Signal) -> str | None:
    url = signal.url or ""
    path = urlsplit(url).path.strip("/")
    if "/abs/" in url and path:
        return path.split("/")[-1].casefold()
    match = re.search(r"\b(arxiv:)?(\d{4}\.\d{4,5}(?:v\d+)?)\b", f"{signal.title} {signal.summary or ''}", re.I)
    if match:
        return match.group(2).casefold()
    return None


def _titleize_technology(normalized: str) -> str:
    cleaned = normalized.replace("_", " ").strip()
    return " ".join(word.capitalize() for word in cleaned.split())


def _canonical_name(value: str) -> str:
    text = str(value).strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _clean_strings(values: list[str]) -> list[str]:
    return [text for text in (str(value).strip() for value in values) if text]


def _dedupe_by_key(items: list[Any], *, key) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for item in items:
        marker = key(item)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(item)
    return result
