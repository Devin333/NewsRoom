from __future__ import annotations

from business.foundation import (
    AnalysisContext,
    Claim,
    ClaimModality,
    ClaimPolarity,
    ClaimType,
    Confidence,
    Entity,
    ObjectRef,
    Signal,
    Technology,
    Topic,
    build_stable_id,
)


class ClaimExtractor:
    def extract(
        self,
        signal: Signal,
        context: AnalysisContext | None = None,
        *,
        entities: list[Entity] | None = None,
        topics: list[Topic] | None = None,
        technologies: list[Technology] | None = None,
    ) -> list[Claim]:
        technologies = technologies or []
        claims: list[Claim] = []
        for technology in technologies:
            if signal.signal_type.value == "paper":
                claims.append(
                    self._claim(signal, technology, "paper", "proposes", ClaimType.TECHNICAL_METHOD, ClaimPolarity.NEUTRAL, ClaimModality.REPORTED, 0.78)
                )
            elif signal.signal_type.value == "github_project":
                claims.append(
                    self._claim(signal, technology, "project", "implements", ClaimType.IMPLEMENTATION_CLAIM, ClaimPolarity.POSITIVE, ClaimModality.ASSERTED, 0.76)
                )
            elif signal.signal_type.value == "community_discussion":
                claims.append(
                    self._claim(signal, technology, "community_thread", "discusses", ClaimType.COMMUNITY_FEEDBACK, ClaimPolarity.MIXED, ClaimModality.REPORTED, 0.66)
                )
            elif signal.signal_type.value == "ai_news":
                claims.append(
                    self._claim(signal, technology, "news_item", "adopts", ClaimType.ADOPTION_CLAIM, ClaimPolarity.POSITIVE, ClaimModality.REPORTED, 0.72)
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
                    confidence=Confidence(value=0.52, factors=[], reason="fallback community feedback claim", evidence_count=1),
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
                    confidence=Confidence(value=0.55, factors=[], reason="fallback paper method claim", evidence_count=1),
                )
            )
        return claims

    def _claim(
        self,
        signal: Signal,
        technology: Technology,
        subject_type: str,
        predicate: str,
        claim_type: ClaimType,
        polarity: ClaimPolarity,
        modality: ClaimModality,
        confidence: float,
    ) -> Claim:
        return Claim(
            claim_id=build_stable_id("claim", signal.signal_id, technology.technology_id, predicate),
            signal_id=signal.signal_id,
            claim_type=claim_type,
            text=f"{signal.title} {predicate} {technology.name}",
            subject_ref=ObjectRef(object_type=subject_type, object_id=signal.signal_id, label=signal.title),
            predicate=predicate,
            object_ref=ObjectRef(object_type="technology", object_id=technology.technology_id, label=technology.name),
            polarity=polarity,
            modality=modality,
            confidence=Confidence(value=confidence, factors=[], reason=f"{predicate} claim rule", evidence_count=1),
        )
