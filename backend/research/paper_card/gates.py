from __future__ import annotations

from backend.research.domain.common import GateResult
from backend.research.paper_card.models import ResearchPaperCard


def validate_paper_card_required_fields(card: ResearchPaperCard) -> GateResult:
    missing = [
        field_name
        for field_name in ("paper_id", "title", "source_url")
        if not str(getattr(card, field_name, "") or "").strip()
    ]
    if missing:
        return GateResult.fail("PaperCardRequiredFieldGate", "missing required fields", metadata={"missing": missing})
    return GateResult.pass_("PaperCardRequiredFieldGate")


def validate_github_metrics_source(card: ResearchPaperCard) -> GateResult:
    has_metric = card.github_stars is not None or card.github_forks is not None or card.github_star_growth_daily is not None
    if not has_metric:
        return GateResult.pass_("PaperCardGithubMetricGate", metadata={"metrics_present": False})
    metric_source = str(card.metadata.get("github_metrics_source") or "")
    if metric_source not in {
        "github_api",
        "github_graphql",
        "github_repository_api",
        "github_repository_port",
    }:
        return GateResult.fail(
            "PaperCardGithubMetricGate",
            "GitHub metrics must come from a real GitHub data source port",
            metadata={"github_metrics_source": metric_source or None},
        )
    return GateResult.pass_("PaperCardGithubMetricGate", metadata={"github_metrics_source": metric_source})


def validate_paper_card_summary_evidence(card: ResearchPaperCard) -> GateResult:
    if card.three_minute_read is None:
        return GateResult.pass_("PaperCardSummaryEvidenceGate", metadata={"summary_present": False})
    if not card.three_minute_read.evidence_refs:
        return GateResult.fail("PaperCardSummaryEvidenceGate", "three_minute_read requires evidence refs")
    return GateResult.pass_("PaperCardSummaryEvidenceGate")


def validate_paper_card_code_url(card: ResearchPaperCard) -> GateResult:
    if card.code_url and not card.github_repo:
        return GateResult.fail("PaperCardCodeUrlGate", "code_url requires normalized github_repo")
    return GateResult.pass_("PaperCardCodeUrlGate")


__all__ = [
    "validate_github_metrics_source",
    "validate_paper_card_code_url",
    "validate_paper_card_required_fields",
    "validate_paper_card_summary_evidence",
]
