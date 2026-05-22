from __future__ import annotations

from business.evaluation.board_eval_case import BoardEvalCase


BOARD_TYPES = ("ai_news", "project_radar", "paper_radar", "community_pulse")


def board_eval_cases() -> list[BoardEvalCase]:
    cases: list[BoardEvalCase] = []
    for board_type in BOARD_TYPES:
        cases.extend(_cases_for_board(board_type))
    return cases


def _cases_for_board(board_type: str) -> list[BoardEvalCase]:
    signal_type = {
        "ai_news": "ai_news",
        "project_radar": "github_project",
        "paper_radar": "paper",
        "community_pulse": "community_discussion",
    }[board_type]
    expected_tags = {
        "ai_news": ["ai_news", "product_update"],
        "project_radar": ["github", "project"],
        "paper_radar": ["paper", "arxiv"],
        "community_pulse": ["community", "discussion"],
    }[board_type]
    return [
        BoardEvalCase(
            case_id=f"{board_type}-happy",
            board_type=board_type,
            topic="Agent Memory",
            signals=[sample_signal(signal_type, index=1)],
            expected_min_cards=1,
            expected_tags=expected_tags,
            expected_entities=["Agent Memory"],
            expected_quality_min=0.5,
            expected_subscription_tags=expected_tags,
        ),
        BoardEvalCase(
            case_id=f"{board_type}-low-quality-source",
            board_type=board_type,
            topic="Agent Memory",
            signals=[sample_signal(signal_type, index=2, reliability="low")],
            expected_min_cards=1,
            expected_tags=expected_tags,
            expected_entities=["Agent Memory"],
            expected_quality_min=0.4,
            expected_subscription_tags=expected_tags,
        ),
        BoardEvalCase(
            case_id=f"{board_type}-duplicate-signals",
            board_type=board_type,
            topic="Agent Memory",
            signals=[sample_signal(signal_type, index=3), sample_signal(signal_type, index=3)],
            expected_min_cards=1,
            expected_tags=expected_tags,
            expected_entities=["Agent Memory"],
            expected_quality_min=0.5,
            expected_subscription_tags=expected_tags,
        ),
        BoardEvalCase(
            case_id=f"{board_type}-sparse-signal",
            board_type=board_type,
            topic="Agent Memory",
            signals=[sample_signal(signal_type, index=4, sparse=True)],
            expected_min_cards=1,
            expected_tags=expected_tags,
            expected_entities=["Agent Memory"],
            expected_quality_min=0.4,
            expected_subscription_tags=expected_tags,
        ),
        BoardEvalCase(
            case_id=f"{board_type}-mixed-irrelevant",
            board_type=board_type,
            topic="Agent Memory",
            signals=[
                sample_signal(signal_type, index=5),
                sample_signal("ai_news" if signal_type != "ai_news" else "paper", index=6),
            ],
            expected_min_cards=1,
            expected_tags=expected_tags,
            expected_entities=["Agent Memory"],
            expected_quality_min=0.5,
            expected_subscription_tags=expected_tags,
        ),
    ]


def sample_signal(signal_type: str, *, index: int = 1, reliability: str = "high", sparse: bool = False) -> dict[str, object]:
    source_type = {
        "ai_news": "rss",
        "github_project": "github",
        "paper": "arxiv",
        "community_discussion": "hackernews",
    }[signal_type]
    summary = "Agent Memory improves workflow orchestration and evidence quality." if not sparse else "Agent Memory update."
    return {
        "source_item_id": f"{signal_type}-{index}",
        "source_id": f"{signal_type}-source",
        "source_name": "OpenAI Blog" if signal_type == "ai_news" else "Source",
        "source_type": source_type,
        "title": "Agent Memory update",
        "summary": summary,
        "content": summary,
        "url": f"https://example.com/{signal_type}/{index}",
        "language": "en",
        "authors": ["Alice"],
        "tags": ["ai", "agent memory"],
        "fetched_at": "2026-05-19T01:00:00Z",
        "published_at": "2026-05-19T00:00:00Z",
        "metadata": {"source_reliability": reliability, "source_authority_score": 0.9 if reliability == "high" else 0.35},
    }


__all__ = ["BOARD_TYPES", "board_eval_cases", "sample_signal"]
