from __future__ import annotations

from tests.architecture._helpers import PROJECT_ROOT, token_violations


FRAMEWORK_ROOT = PROJECT_ROOT / "framework"
FORBIDDEN_TOKENS = (
    "DailyIntelligence",
    "DailyNews",
    "AINews",
    "PaperRadar",
    "ProjectRadar",
    "CommunityPulse",
    "CrossBoard",
    "FinalReport",
    "ReportSection",
    "EvidenceBundle",
    "EvidenceItem",
    "SourceItem",
    "RSS",
    "Arxiv",
    "GitHubRepo",
)


def test_framework_does_not_contain_business_tokens() -> None:
    assert token_violations(FRAMEWORK_ROOT, FORBIDDEN_TOKENS) == []
