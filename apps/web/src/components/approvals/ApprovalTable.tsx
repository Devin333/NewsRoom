"use client"

import { useState } from "react"
import { StatusBadge } from "@/components/common/StatusBadge"
import { formatDateTime } from "@/lib/format"
import { safeApiPost } from "@/lib/api-client"
import type { ApprovalItem, ApprovalResumeContext, ApprovalWorkflowResumeResult } from "@/lib/types"

export function ApprovalTable({ approvals }: { approvals: ApprovalItem[] }) {
  const [loading, setLoading] = useState<string | null>(null)
  const [results, setResults] = useState<Record<string, string>>({})

  async function act(approvalId: string, action: string) {
    setLoading(`${approvalId}:${action}`)
    let msg = ""
    if (action === "approve" || action === "reject") {
      const res = await safeApiPost(`/api/v1/approvals/${approvalId}/${action}`, {})
      msg = res.ok ? `${action}d` : (res.errorMessage ?? "failed")
    } else if (action === "resume-context") {
      const res = await safeApiPost<ApprovalResumeContext>(`/api/v1/approvals/${approvalId}/resume-context`, {})
      msg = res.ok ? "Context retrieved" : (res.errorMessage ?? "failed")
    } else if (action === "resume-workflow") {
      const res = await safeApiPost<ApprovalWorkflowResumeResult>(`/api/v1/approvals/${approvalId}/resume-workflow`, {})
      msg = res.ok ? `Workflow resumed → ${res.data?.run_id ?? ""}` : (res.errorMessage ?? "failed")
    }
    setResults((p) => ({ ...p, [approvalId]: msg }))
    setLoading(null)
  }

  if (!approvals.length) return <p className="text-sm text-muted">No pending approvals.</p>

  return (
    <div className="space-y-3">
      {approvals.map((a) => (
        <div key={a.approval_id} className="rounded-lg border border-line bg-white p-4 shadow-card">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <StatusBadge status={a.risk_level ?? a.status} />
                <span className="font-mono text-xs text-subtle">{a.approval_id.slice(0, 12)}…</span>
              </div>
              <p className="mt-1.5 text-sm font-medium text-ink">{a.requested_action ?? "Approval required"}</p>
              {a.reason && <p className="mt-0.5 text-xs text-muted">{a.reason}</p>}
              <p className="mt-1 text-xs text-subtle">
                {a.requested_by && <span>by {a.requested_by} · </span>}
                {a.created_at && formatDateTime(a.created_at)}
              </p>
            </div>
            <div className="flex shrink-0 flex-wrap gap-2">
              {(["approve", "reject", "resume-context", "resume-workflow"] as const).map((action) => {
                const isLoading = loading === `${a.approval_id}:${action}`
                const variant = action === "approve"
                  ? "bg-good text-white hover:bg-good/90"
                  : action === "reject"
                  ? "bg-bad text-white hover:bg-bad/90"
                  : "border border-line bg-white text-ink hover:bg-surface"
                return (
                  <button
                    key={action}
                    onClick={() => act(a.approval_id, action)}
                    disabled={!!loading}
                    className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-50 ${variant}`}
                  >
                    {isLoading ? "…" : action.replace("-", " ")}
                  </button>
                )
              })}
            </div>
          </div>
          {results[a.approval_id] && (
            <p className="mt-2 text-xs text-muted">{results[a.approval_id]}</p>
          )}
        </div>
      ))}
    </div>
  )
}
