"""Evidence construction package."""

from backend.layers.relation.evidence.builder import EvidenceBuilder
from backend.layers.relation.evidence.claim_verifier import ClaimExtractor, ClaimVerifier
from backend.layers.relation.evidence.models import (
    Claim,
    EvidenceBuildResult,
    EvidenceBundle,
    EvidenceItem,
    EvidenceScore,
    Lineage,
    VerifiedClaim,
    VerifiedFindings,
)

__all__ = [
    "Claim",
    "ClaimExtractor",
    "ClaimVerifier",
    "EvidenceBuildResult",
    "EvidenceBuilder",
    "EvidenceBundle",
    "EvidenceItem",
    "EvidenceScore",
    "Lineage",
    "VerifiedClaim",
    "VerifiedFindings",
]
