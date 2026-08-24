"use client"

import { useState } from "react"
import { StatusBadge } from "@/components/common/StatusBadge"
import { safeApiPost } from "@/lib/api-client"
import { useToast } from "@/components/common/Toast"
import type { GraphWaitItem } from "@/lib/types"

export function WaitTable({ waits }: { waits: GraphWaitItem[] }) {
  const toast = useToast()
  const [loading, setLoading] = useState<string | null>(null)

  async function decide(wait: GraphWaitItem, approved: boolean) {
    if (!wait.approval_id) {
      toast("该 Wait 没有关联 approval identity", "error")
      return
    }
    const key = `${wait.run_id}:${wait.node_instance_id}:${approved}`
    setLoading(key)
    const res = await safeApiPost(
      `/api/v2/graph-runs/${encodeURIComponent(wait.run_id)}/waits/${encodeURIComponent(wait.node_instance_id)}/approval`,
      { approval_id: wait.approval_id, approved },
    )
    setLoading(null)
    res.ok ? toast(approved ? "Approval 已提交" : "Approval 已拒绝", "success") : toast(res.errorMessage ?? "提交失败", "error")
  }

  if (!waits.length) return <p className="text-sm text-muted">No pending Graph Waits.</p>

  return (
    <div className="space-y-3">
      {waits.map((wait) => (
        <div key={`${wait.run_id}:${wait.node_instance_id}`} className="rounded-lg border border-line bg-white p-4 shadow-card">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <StatusBadge status={wait.status} />
                <span className="font-mono text-xs text-subtle">{wait.approval_id ?? "approval unavailable"}</span>
              </div>
              <p className="mt-1.5 text-sm font-medium text-ink">Graph approval Wait</p>
              <p className="mt-1 text-xs text-subtle">Run {wait.run_id} · Node {wait.node_instance_id}</p>
              <p className="mt-1 text-xs text-subtle">{wait.graph_ref} · {wait.graph_checksum}</p>
            </div>
            <div className="flex shrink-0 gap-2">
              {[true, false].map((approved) => {
                const key = `${wait.run_id}:${wait.node_instance_id}:${approved}`
                return (
                  <button
                    key={String(approved)}
                    onClick={() => decide(wait, approved)}
                    disabled={Boolean(loading) || !wait.approval_id}
                    className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-50 ${approved ? "bg-good text-white hover:bg-good/90" : "bg-bad text-white hover:bg-bad/90"}`}
                  >
                    {loading === key ? "..." : approved ? "Approve" : "Reject"}
                  </button>
                )
              })}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
