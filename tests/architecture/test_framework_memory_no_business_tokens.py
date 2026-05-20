from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MEMORY_ROOT = PROJECT_ROOT / "framework" / "memory"
FORBIDDEN_TOKENS = (
    "FinalReport",
    "EvidenceBundle",
    "ReportSection",
    "DailyIntelligence",
    "PaperRadar",
    "ProjectRadar",
    "CommunityPulse",
    "CrossBoard",
    "SourceItem",
    "Qdrant",
    "Postgres",
    "Redis",
)


def test_framework_memory_has_no_business_or_storage_tokens() -> None:
    violations: list[str] = []
    for path in MEMORY_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_TOKENS:
            if token in text:
                violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {token}")

    assert violations == []
