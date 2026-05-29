from __future__ import annotations

from business.projects.models import EvolutionProposal, UserProjectInteractionEvent, WatchlistItem, stable_id
from business.projects.repository import ProjectStateRepository


class ProjectEvolutionService:
    def __init__(self, state_repository: ProjectStateRepository) -> None:
        self.state_repository = state_repository

    def record_interaction(self, event: UserProjectInteractionEvent) -> UserProjectInteractionEvent:
        def update(state):
            interactions = [*state.interaction_events, event]
            proposals = list(state.evolution_proposals)
            if _should_propose_watchlist_update(state.watchlist_items, interactions) and not any(
                proposal.proposal_type == "collection_recommendation_update" for proposal in proposals
            ):
                proposals.append(
                    EvolutionProposal(
                        id=stable_id("evolution", "collection_recommendation_update", len(interactions)),
                        proposal_type="collection_recommendation_update",
                        title="Tune Projects collection recommendations",
                        summary="Watchlist and interaction events suggest collection recommendations may need re-weighting.",
                        evidence=[
                            f"watchlist_items={len(state.watchlist_items)}",
                            f"interaction_events={len(interactions)}",
                        ],
                        proposed_change={"strategy": "increase_watchlist_weight"},
                        expected_impact="Improve relevance of project collections and watch packs.",
                        risk_level="low",
                    )
                )
            return state.model_copy(
                update={
                    "interaction_events": interactions,
                    "evolution_proposals": proposals,
                }
            )

        self.state_repository.update(update)
        return event

    def proposals(self) -> list[EvolutionProposal]:
        return self.state_repository.load().evolution_proposals

    def _refresh_proposals(self) -> None:
        state = self.state_repository.load()
        proposals = list(state.evolution_proposals)
        if _should_propose_watchlist_update(state.watchlist_items, state.interaction_events) and not any(
            proposal.proposal_type == "collection_recommendation_update" for proposal in proposals
        ):
            proposals.append(
                EvolutionProposal(
                    id=stable_id("evolution", "collection_recommendation_update", len(state.interaction_events)),
                    proposal_type="collection_recommendation_update",
                    title="Tune Projects collection recommendations",
                    summary="Watchlist and interaction events suggest collection recommendations may need re-weighting.",
                    evidence=[
                        f"watchlist_items={len(state.watchlist_items)}",
                        f"interaction_events={len(state.interaction_events)}",
                    ],
                    proposed_change={"strategy": "increase_watchlist_weight"},
                    expected_impact="Improve relevance of project collections and watch packs.",
                    risk_level="low",
                )
            )
            self.state_repository.replace_evolution_proposals(proposals)


def _should_propose_watchlist_update(
    watchlist_items: list[WatchlistItem],
    interaction_events: list[UserProjectInteractionEvent],
) -> bool:
    return len(watchlist_items) >= 3 and len(interaction_events) >= 5
