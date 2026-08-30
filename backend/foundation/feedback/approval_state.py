from __future__ import annotations

PROPOSED = "proposed"
APPROVED = "approved"
REJECTED = "rejected"
APPLIED = "applied"
SUPERSEDED = "superseded"

APPROVABLE_STATUSES = {PROPOSED}
APPLICABLE_STATUSES = {APPROVED, APPLIED}

__all__ = [
    "APPLICABLE_STATUSES",
    "APPROVABLE_STATUSES",
    "APPLIED",
    "APPROVED",
    "PROPOSED",
    "REJECTED",
    "SUPERSEDED",
]
