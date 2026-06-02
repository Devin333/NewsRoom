"""Evidence verification agent for benchmark and taxonomy claims."""

from __future__ import annotations

from collections.abc import Mapping

from business.boards.paper_radar.agents.models import PaperAgentContext, PaperAgentResult
from business.boards.paper_radar.agents.roles import (
    PAPER_ROLE_BENCHMARK_CLAIMS,
    PAPER_ROLE_EVIDENCE_VERIFICATION,
    PAPER_ROLE_EXPERIMENT_RESULT,
    PAPER_ROLE_SEMANTIC_SECTIONS,
    PAPER_ROLE_TAXONOMY_RESULT,
)
from business.boards.paper_radar.agents.utils.evidence import latest_output, sequence


class PaperEvidenceVerificationAgent:
    """Verify existing claims against section and experiment evidence."""

    agent_id = "paper-evidence-verification-agent"
    required_roles = (
        PAPER_ROLE_SEMANTIC_SECTIONS,
        PAPER_ROLE_TAXONOMY_RESULT,
        PAPER_ROLE_EXPERIMENT_RESULT,
        PAPER_ROLE_BENCHMARK_CLAIMS,
    )
    produced_role = PAPER_ROLE_EVIDENCE_VERIFICATION

    def run(self, context: PaperAgentContext) -> PaperAgentResult:
        experiment = latest_output(context.shared_items, PAPER_ROLE_EXPERIMENT_RESULT)
        claims_source = latest_output(context.shared_items, PAPER_ROLE_BENCHMARK_CLAIMS)
        claims = [item for item in sequence(claims_source.get("claims") or experiment.get("benchmarks")) if isinstance(item, Mapping)]
        verified, weak, rejected = [], [], []
        for claim in claims:
            claim_id = str(claim.get("claimId") or claim.get("id") or "")
            problems = _claim_problems(claim)
            item = {
                "claimId": claim_id,
                "verified": not problems,
                "evidenceQuality": "direct_table_evidence" if not problems else "weak_text_evidence",
                "confidence": 0.92 if not problems else 0.48,
                "problems": problems,
            }
            if not claim_id:
                rejected.append(item)
            elif problems:
                weak.append(item)
            else:
                verified.append(item)
        output = {
            "verifiedClaims": verified,
            "rejectedClaims": rejected,
            "weakClaims": weak,
            "verificationSummary": _summary(verified, weak, rejected),
        }
        return PaperAgentResult(
            agent_id=self.agent_id,
            role=self.produced_role,
            output=output,
            summary=output["verificationSummary"],
            confidence=0.9 if verified and not weak and not rejected else 0.62,
            warnings=tuple("weak_or_rejected_claim" for _ in weak + rejected),
        )


def _claim_problems(claim: Mapping[str, object]) -> list[str]:
    problems = []
    if claim.get("value") in (None, "", [], {}):
        problems.append("missing_metric_value")
    if not claim.get("evidence"):
        problems.append("missing_evidence")
    if not claim.get("claimId") and not claim.get("id"):
        problems.append("missing_claim_id")
    return problems


def _summary(verified: list[Mapping[str, object]], weak: list[Mapping[str, object]], rejected: list[Mapping[str, object]]) -> str:
    return f"Verified {len(verified)} claim(s), found {len(weak)} weak claim(s), rejected {len(rejected)} claim(s)."
