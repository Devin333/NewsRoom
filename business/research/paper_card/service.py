from __future__ import annotations

from business.research.domain.analysis import ThreeMinuteRead
from business.research.domain.paper import ResearchPaper
from business.research.paper_card.models import ResearchPaperCard


class PaperCardBuilder:
    """Combines verified domain data into a backend-facing paper card."""

    def build(
        self,
        *,
        paper: ResearchPaper,
        three_minute_read: ThreeMinuteRead | None = None,
        taxonomy: dict[str, list[str]] | None = None,
        github: dict[str, object] | None = None,
        reader_payload_status: str = "missing",
        metadata: dict[str, object] | None = None,
    ) -> ResearchPaperCard:
        taxonomy = taxonomy or {}
        github = github or {}
        merged_metadata = dict(metadata or {})
        if github:
            github_metadata = github.get("metadata") if isinstance(github.get("metadata"), dict) else {}
            merged_metadata.setdefault("github_metrics_source", github.get("metrics_source") or github_metadata.get("metrics_source"))
        return ResearchPaperCard(
            paper_id=paper.paper_id,
            title=paper.title,
            authors=paper.authors,
            abstract=paper.abstract,
            published_at=paper.published_at,
            source_url=paper.source_url or "",
            pdf_url=paper.pdf_url,
            code_url=paper.code_url,
            github_repo=github.get("repo_url") if github else None,
            github_stars=github.get("stars") if isinstance(github.get("stars"), int) else None,
            github_star_growth_daily=(
                float(github["star_growth_daily"]) if github.get("star_growth_daily") is not None else None
            ),
            github_forks=github.get("forks") if isinstance(github.get("forks"), int) else None,
            github_last_commit_at=github.get("last_commit_at"),
            github_license=github.get("license") if github.get("license") is not None else None,
            three_minute_read=three_minute_read,
            domains=taxonomy.get("domains", []),
            areas=taxonomy.get("areas", []),
            tasks=taxonomy.get("tasks", []),
            methods=taxonomy.get("methods", []),
            benchmarks=taxonomy.get("benchmarks", []),
            reader_payload_status=reader_payload_status,
            metadata=merged_metadata,
        )


__all__ = ["PaperCardBuilder"]
