from __future__ import annotations

import json
from pathlib import Path

from core.framework.workers.approval import (
    ApprovalDecision,
    ApprovalNotFoundError,
    ApprovalRequest,
    ApprovalStatus,
)


APPROVAL_STORE_SCHEMA_VERSION = "approval_store.v1"


class LocalJsonApprovalStore:
    def __init__(self, path: str | Path = ".newsroom/approvals/approvals.json") -> None:
        self.path = Path(path)

    def list_approvals(self, *, status: ApprovalStatus | str | None = None) -> list[ApprovalRequest]:
        records = sorted(self._read_records().values(), key=lambda request: request.created_at)
        if status is None:
            return records
        actual_status = ApprovalStatus(status)
        return [request for request in records if request.status == actual_status]

    def get_approval(self, approval_id: str) -> ApprovalRequest:
        records = self._read_records()
        try:
            return records[approval_id]
        except KeyError as exc:
            raise ApprovalNotFoundError(approval_id) from exc

    def upsert_approval(self, request: ApprovalRequest) -> ApprovalRequest:
        records = self._read_records()
        records[request.approval_id] = request
        self._write_records(records)
        return request

    def record_decision(
        self,
        approval_id: str,
        *,
        decision: ApprovalDecision,
    ) -> ApprovalRequest:
        request = self.get_approval(approval_id)
        decided = request.with_decision(decision)
        self.upsert_approval(decided)
        return decided

    def _read_records(self) -> dict[str, ApprovalRequest]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        approvals = payload.get("approvals", [])
        records = [ApprovalRequest.from_dict(item) for item in approvals]
        return {record.approval_id: record for record in records}

    def _write_records(self, records: dict[str, ApprovalRequest]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": APPROVAL_STORE_SCHEMA_VERSION,
            "approvals": [
                record.to_dict()
                for record in sorted(records.values(), key=lambda item: item.created_at)
            ],
        }
        temp_path = self.path.with_name(f"{self.path.name}.tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp_path.replace(self.path)
