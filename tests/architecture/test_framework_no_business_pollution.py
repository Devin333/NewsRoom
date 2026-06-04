from __future__ import annotations

from tests.architecture._helpers import PROJECT_ROOT, token_violations


FRAMEWORK_ROOT = PROJECT_ROOT / "framework"
FORBIDDEN_BUSINESS_TOKENS = (
    "paper_reader",
    "PaperReader",
    "paper_radar",
    "PaperRadar",
    "daily_intelligence",
    "DailyIntelligence",
    "project_radar",
    "ProjectRadar",
    "community_pulse",
    "CommunityPulse",
    "newsroom business board",
)
ALLOWED_LEGACY_GUARDRAIL_REFERENCES = {
    "framework/harness/skills/evolution/gates.py: paper_radar",
}


def test_framework_production_code_has_no_business_pollution_tokens() -> None:
    violations = [
        violation
        for violation in token_violations(FRAMEWORK_ROOT, FORBIDDEN_BUSINESS_TOKENS)
        if violation not in ALLOWED_LEGACY_GUARDRAIL_REFERENCES
    ]

    assert violations == []
