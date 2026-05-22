from __future__ import annotations

import json
from pathlib import Path

from business.foundation.feedback.approval_state import APPLIED, APPROVED, REJECTED
from business.foundation.feedback.improvement_proposal import ImprovementProposal


class InMemoryImprovementProposalStore:
    def __init__(self) -> None:
        self._proposals: dict[str, ImprovementProposal] = {}

    def save(self, proposal: ImprovementProposal) -> ImprovementProposal:
        self._proposals[proposal.proposal_id] = proposal
        return proposal

    def get(self, proposal_id: str) -> ImprovementProposal | None:
        return self._proposals.get(proposal_id)

    def list(self, status: str | None = None) -> list[ImprovementProposal]:
        values = list(self._proposals.values())
        if status is not None:
            values = [proposal for proposal in values if proposal.status == status]
        return sorted(values, key=lambda proposal: proposal.created_at)

    def approve(self, proposal_id: str) -> ImprovementProposal:
        return self._set_status(proposal_id, APPROVED)

    def reject(self, proposal_id: str) -> ImprovementProposal:
        return self._set_status(proposal_id, REJECTED)

    def mark_applied(self, proposal_id: str) -> ImprovementProposal:
        return self._set_status(proposal_id, APPLIED)

    def _set_status(self, proposal_id: str, status: str) -> ImprovementProposal:
        proposal = self.get(proposal_id)
        if proposal is None:
            raise KeyError(proposal_id)
        updated = proposal.with_status(status)
        self.save(updated)
        return updated


class LocalJsonImprovementProposalStore(InMemoryImprovementProposalStore):
    def __init__(self, root: str | Path) -> None:
        super().__init__()
        self.root = Path(root)
        self.path = self.root / "improvement_proposals.json"
        self._load()

    def save(self, proposal: ImprovementProposal) -> ImprovementProposal:
        saved = super().save(proposal)
        self._flush()
        return saved

    def _set_status(self, proposal_id: str, status: str) -> ImprovementProposal:
        updated = super()._set_status(proposal_id, status)
        self._flush()
        return updated

    def _load(self) -> None:
        if not self.path.exists():
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        for item in payload if isinstance(payload, list) else []:
            proposal = ImprovementProposal.from_dict(dict(item))
            self._proposals[proposal.proposal_id] = proposal

    def _flush(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = [proposal.to_dict() for proposal in self.list()]
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


__all__ = ["InMemoryImprovementProposalStore", "LocalJsonImprovementProposalStore"]
