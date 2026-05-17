"use client"

import { useState, useTransition } from "react"
import { useRouter } from "next/navigation"
import { ErrorState } from "@/components/common/ErrorState"
import { StatusBadge } from "@/components/common/StatusBadge"
import { safeApiPost } from "@/lib/api-client"
import { formatDateTime } from "@/lib/format"
import type { ApprovalItem } from "@/lib/types"

export function ApprovalTable({ approvals }: { approvals: ApprovalItem[] }) {
  const router = useRouter()
  const [error, setError] = useState<{ message?: string; requestId?: string } | null>(null)
  const [isPending, startTransition] = useTransition()

  async function decide(approvalId: string, decision: "approve" | "reject") {
    if (!window.confirm(`${decision} approval ${approvalId}?`)) {
      return
    }
    setError(null)
    const response = await safeApiPost(`/api/v1/approvals/${encodeURIComponent(approvalId)}/${decision}`, {
      decided_by: "web-console"
    })
    if (response.ok) {
      startTransition(() => router.refresh())
    } else {
      setError({ message: response.errorMessage, requestId: response.requestId })
    }
  }

  if (!approvals.length) {
    return <div className="rounded-lg border border-line bg-white p-4 text-sm text-muted">No pending approvals.</div>
  }

  return (
    <div className="space-y-3">
      {error ? <ErrorState message={error.message} requestId={error.requestId} /> : null}
      <div className="overflow-x-auto rounded-lg border border-line bg-white">
        <table className="w-full table-fixed border-collapse text-left text-sm">
          <thead className="bg-surface text-xs uppercase text-muted">
            <tr>
              <th className="w-48 px-4 py-3 font-medium">Approval</th>
              <th className="w-44 px-4 py-3 font-medium">Action</th>
              <th className="w-32 px-4 py-3 font-medium">Status</th>
              <th className="w-40 px-4 py-3 font-medium">Risk</th>
              <th className="w-44 px-4 py-3 font-medium">Created</th>
              <th className="w-48 px-4 py-3 font-medium">Decision</th>
            </tr>
          </thead>
          <tbody>
            {approvals.map((approval) => (
              <tr key={approval.approval_id} className="border-t border-line">
                <td className="truncate px-4 py-3 font-medium text-ink">{approval.approval_id}</td>
                <td className="truncate px-4 py-3 text-muted">{approval.requested_action ?? "unknown"}</td>
                <td className="px-4 py-3">
                  <StatusBadge status={approval.status} />
                </td>
                <td className="truncate px-4 py-3 text-muted">{approval.risk_level ?? "n/a"}</td>
                <td className="truncate px-4 py-3 text-muted">{formatDateTime(approval.created_at)}</td>
                <td className="flex gap-2 px-4 py-3">
                  <button
                    className="rounded-md border border-good/30 px-3 py-1 text-xs font-medium text-good disabled:opacity-50"
                    disabled={isPending}
                    onClick={() => decide(approval.approval_id, "approve")}
                    type="button"
                  >
                    Approve
                  </button>
                  <button
                    className="rounded-md border border-bad/30 px-3 py-1 text-xs font-medium text-bad disabled:opacity-50"
                    disabled={isPending}
                    onClick={() => decide(approval.approval_id, "reject")}
                    type="button"
                  >
                    Reject
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
