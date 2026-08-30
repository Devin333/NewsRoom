from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, cast

from backend.memory.intelligence_builder import normalize_text_key, safe_str_list, stable_id
from backend.memory.intelligence_models import ClaimMemory, EntityMemory, EvidenceMemory, IntelligenceMemoryBundle


DEFAULT_ALIAS_MAP = {
    "open ai": "OpenAI",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "claude": "Claude",
    "langgraph": "LangGraph",
    "qwen": "Qwen",
    "qwen3": "Qwen",
    "github": "GitHub",
}


@dataclass(frozen=True)
class EntityCandidate:
    name: str
    entity_type: str = "unknown"
    source: str = "text"
    confidence: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)

    def normalized_name(self) -> str:
        return normalize_text_key(self.name)


@dataclass(frozen=True)
class EntityResolutionResult:
    entities: list[EntityMemory]
    aliases_used: dict[str, str] = field(default_factory=dict)
    unresolved_candidates: list[EntityCandidate] = field(default_factory=list)

    def entity_ids(self) -> list[str]:
        return [entity.entity_id for entity in self.entities]


class EntityResolver:
    def __init__(
        self,
        *,
        alias_map: dict[str, str] | None = None,
        known_entities: dict[str, EntityMemory] | None = None,
    ) -> None:
        raw_aliases = dict(DEFAULT_ALIAS_MAP)
        raw_aliases.update(alias_map or {})
        self.alias_map = {normalize_text_key(alias): canonical for alias, canonical in raw_aliases.items()}
        self.known_entities = dict(known_entities or {})

    def resolve_bundle(self, bundle: IntelligenceMemoryBundle) -> EntityResolutionResult:
        candidates: list[EntityCandidate] = []
        if bundle.topic:
            candidates.append(
                EntityCandidate(
                    name=bundle.topic,
                    entity_type="topic",
                    source="topic",
                    confidence=1.0,
                )
            )
        for entity in bundle.entities:
            candidates.append(
                EntityCandidate(
                    name=entity.canonical_name,
                    entity_type=entity.entity_type,
                    source="bundle.entity",
                    confidence=1.0,
                    metadata={
                        "entity_id": entity.entity_id,
                        "aliases": list(entity.aliases),
                        "summary": entity.summary,
                        "external_refs": dict(entity.external_refs),
                        "importance_score": entity.importance_score,
                        "trend_score": entity.trend_score,
                        **dict(entity.metadata),
                    },
                )
            )
        for evidence in bundle.evidence:
            candidates.extend(self.extract_candidates_from_evidence(evidence))
        for claim in bundle.claims:
            candidates.extend(self.extract_candidates_from_claim(claim))
        return self._resolve_candidates(candidates)

    def resolve_texts(
        self,
        texts: list[str],
        *,
        topic: str | None = None,
    ) -> EntityResolutionResult:
        candidates: list[EntityCandidate] = []
        if topic:
            candidates.append(EntityCandidate(name=topic, entity_type="topic", source="topic", confidence=1.0))
        for text in texts:
            candidates.extend(self._extract_alias_candidates(str(text), source="text"))
        return self._resolve_candidates(candidates)

    def extract_candidates_from_evidence(self, evidence: EvidenceMemory) -> list[EntityCandidate]:
        candidates: list[EntityCandidate] = []
        if evidence.topic:
            candidates.append(
                EntityCandidate(name=evidence.topic, entity_type="topic", source="evidence.topic", confidence=1.0)
            )
        if evidence.source_name:
            candidates.append(
                EntityCandidate(
                    name=evidence.source_name,
                    entity_type="source",
                    source="evidence.source_name",
                    confidence=0.9,
                    metadata={"source_id": evidence.source_id} if evidence.source_id else {},
                )
            )
        metadata = dict(evidence.metadata)
        github_repo = _first_text(metadata.get("github_repo"), metadata.get("repo"), metadata.get("repository"))
        if github_repo:
            candidates.append(
                EntityCandidate(
                    name=github_repo,
                    entity_type="repository",
                    source="evidence.metadata.github_repo",
                    confidence=0.95,
                    metadata={"github_repo": github_repo},
                )
            )
        paper_id = _first_text(metadata.get("paper_id"), metadata.get("arxiv_id"))
        if paper_id:
            candidates.append(
                EntityCandidate(
                    name=paper_id,
                    entity_type="paper",
                    source="evidence.metadata.paper_id",
                    confidence=0.95,
                    metadata={"paper_id": paper_id},
                )
            )
        candidates.extend(self._extract_alias_candidates(f"{evidence.title} {evidence.summary}", source="evidence.text"))
        return candidates

    def extract_candidates_from_claim(self, claim: ClaimMemory) -> list[EntityCandidate]:
        candidates = self._extract_alias_candidates(claim.text, source="claim.text")
        if claim.subject_entity_id:
            candidates.append(
                EntityCandidate(
                    name=claim.subject_entity_id,
                    entity_type="unknown",
                    source="claim.subject_entity_id",
                    confidence=0.6,
                    metadata={"entity_id": claim.subject_entity_id},
                )
            )
        if claim.object_entity_id:
            candidates.append(
                EntityCandidate(
                    name=claim.object_entity_id,
                    entity_type="unknown",
                    source="claim.object_entity_id",
                    confidence=0.6,
                    metadata={"entity_id": claim.object_entity_id},
                )
            )
        return candidates

    def canonicalize_name(self, name: str) -> str:
        key = normalize_text_key(name)
        return self.alias_map.get(key) or str(name).strip()

    def infer_entity_type(
        self,
        name: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        payload = dict(metadata or {})
        if payload.get("entity_type"):
            return str(payload["entity_type"])
        if payload.get("github_repo") or "/" in str(name) and not str(name).startswith("http"):
            return "repository"
        if payload.get("paper_id") or payload.get("arxiv_id"):
            return "paper"
        key = normalize_text_key(name)
        if key in {"github"}:
            return "source"
        if key in {"openai", "open ai", "anthropic"}:
            return "organization"
        if key in {"claude", "qwen", "qwen3"}:
            return "model"
        return "unknown"

    def build_entity(self, candidate: EntityCandidate) -> EntityMemory:
        canonical_name = self.canonicalize_name(candidate.name)
        entity_type = candidate.entity_type
        if entity_type == "unknown":
            entity_type = self.infer_entity_type(canonical_name, metadata=candidate.metadata)
        entity_id = str(candidate.metadata.get("entity_id") or stable_entity_id(entity_type, canonical_name))
        external_refs: dict[str, Any] = {}
        for key in ("source_id", "github_repo", "paper_id", "arxiv_id"):
            if candidate.metadata.get(key):
                external_refs[key] = candidate.metadata[key]
        aliases = safe_str_list(candidate.metadata.get("aliases"))
        original = str(candidate.name).strip()
        if original and original.casefold() != canonical_name.casefold():
            aliases.append(original)
        return EntityMemory(
            entity_id=entity_id,
            entity_type=cast(Any, entity_type),
            canonical_name=canonical_name,
            aliases=_unique_text(aliases),
            summary=_optional_text(candidate.metadata.get("summary")),
            importance_score=_safe_float(candidate.metadata.get("importance_score"), 0.0),
            trend_score=_safe_float(candidate.metadata.get("trend_score"), 0.0),
            external_refs=external_refs | _safe_dict(candidate.metadata.get("external_refs")),
            metadata={
                "source": candidate.source,
                "confidence": candidate.confidence,
                **{key: value for key, value in candidate.metadata.items() if key not in {"aliases", "external_refs"}},
            },
        )

    def _resolve_candidates(self, candidates: list[EntityCandidate]) -> EntityResolutionResult:
        entities_by_id: dict[str, EntityMemory] = dict(self.known_entities)
        aliases_used: dict[str, str] = {}
        unresolved: list[EntityCandidate] = []
        for candidate in candidates:
            if not candidate.name.strip():
                unresolved.append(candidate)
                continue
            entity = self.build_entity(candidate)
            canonical_key = normalize_text_key(entity.canonical_name)
            original_key = candidate.normalized_name()
            if original_key and original_key != canonical_key:
                aliases_used[candidate.name] = entity.canonical_name
            matched_alias = _optional_text(candidate.metadata.get("matched_alias"))
            if matched_alias and normalize_text_key(matched_alias) != canonical_key:
                aliases_used[matched_alias] = entity.canonical_name
            existing = self._find_existing_entity(entity, entities_by_id)
            if existing is None:
                entities_by_id[entity.entity_id] = entity
            else:
                merged = existing
                for alias in [entity.canonical_name, *entity.aliases]:
                    merged = merged.with_alias(alias)
                metadata = {**existing.metadata, **entity.metadata}
                external_refs = {**existing.external_refs, **entity.external_refs}
                entities_by_id[existing.entity_id] = replace(
                    merged,
                    summary=merged.summary or entity.summary,
                    importance_score=max(existing.importance_score, entity.importance_score),
                    trend_score=max(existing.trend_score, entity.trend_score),
                    external_refs=external_refs,
                    metadata=metadata,
                )
        return EntityResolutionResult(
            entities=sorted(entities_by_id.values(), key=lambda item: (item.entity_type, item.canonical_name)),
            aliases_used=aliases_used,
            unresolved_candidates=unresolved,
        )

    def _find_existing_entity(
        self,
        entity: EntityMemory,
        entities_by_id: dict[str, EntityMemory],
    ) -> EntityMemory | None:
        if entity.entity_id in entities_by_id:
            return entities_by_id[entity.entity_id]
        names = {normalize_text_key(name) for name in entity.all_names()}
        for existing in entities_by_id.values():
            if normalize_text_key(existing.canonical_name) in names:
                return existing
            if names & {normalize_text_key(name) for name in existing.all_names()}:
                return existing
        return None

    def _extract_alias_candidates(self, text: str, *, source: str) -> list[EntityCandidate]:
        haystack = f" {normalize_text_key(text)} "
        candidates: list[EntityCandidate] = []
        seen: set[str] = set()
        for alias, canonical in self.alias_map.items():
            if f" {alias} " not in haystack or canonical.casefold() in seen:
                continue
            seen.add(canonical.casefold())
            candidates.append(
                EntityCandidate(
                    name=canonical,
                    entity_type=self.infer_entity_type(canonical),
                    source=source,
                    confidence=0.75,
                    metadata={"matched_alias": alias},
                )
            )
        return candidates


def stable_entity_id(entity_type: str, canonical_name: str) -> str:
    return stable_id("entity", entity_type, normalize_text_key(canonical_name), prefix="entity")


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = _optional_text(value)
        if text:
            return text
    return None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _unique_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


__all__ = [
    "DEFAULT_ALIAS_MAP",
    "EntityCandidate",
    "EntityResolutionResult",
    "EntityResolver",
    "stable_entity_id",
]
