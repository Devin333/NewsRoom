from __future__ import annotations

from hashlib import sha256

from domain.sources import RankedSourceItem
from evidence.models import EvidenceBundle, EvidenceItem


class EvidenceBuilder:
    def build(self, ranked_items: list[RankedSourceItem], *, bundle_id: str = "daily") -> EvidenceBundle:
        evidence_items = []
        for ranked in ranked_items:
            item = ranked.item
            evidence_hash = sha256(item.canonical_url.encode("utf-8")).hexdigest()[:16]
            source_lineage = ranked.metadata.get("lineage") or item.metadata.get("lineage") or {}
            evidence_items.append(
                EvidenceItem(
                    evidence_id=f"ev_{evidence_hash}",
                    source_url=item.canonical_url,
                    title=item.title,
                    summary=item.summary or item.title,
                    confidence=round(min(1.0, max(0.1, ranked.final_score)), 4),
                    source_id=item.source_id,
                    metadata={
                        "ranked_item_id": ranked.ranked_item_id,
                        "final_score": ranked.final_score,
                        "rank_reason": ranked.rank_reason,
                        "source_lineage": dict(source_lineage),
                    },
                )
            )
        return EvidenceBundle(bundle_id=bundle_id, items=evidence_items)
