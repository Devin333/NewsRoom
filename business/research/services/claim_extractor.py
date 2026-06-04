from __future__ import annotations

from business.research.domain.evidence import ResearchClaim


class ClaimExtractor:
    def from_candidate_payload(self, payload: list[dict[str, object]]) -> list[ResearchClaim]:
        return [
            ResearchClaim(
                claim_id=str(item.get("claim_id") or item.get("id") or ""),
                text=str(item.get("text") or ""),
                claim_type=str(item.get("claim_type") or "other"),
                section_id=item.get("section_id") if item.get("section_id") is not None else None,
                evidence_ids=[str(ref) for ref in item.get("evidence_ids", [])],
                confidence=float(item.get("confidence", 0.0) or 0.0),
                metadata=dict(item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}),
            )
            for item in payload
        ]


__all__ = ["ClaimExtractor"]
