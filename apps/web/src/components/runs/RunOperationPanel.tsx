"use client"

import { useState } from "react"
import { safeApiPost } from "@/lib/api-client"
import { useToast } from "@/components/common/Toast"
import type { RunOperationResult } from "@/lib/types"

export function RunOperationPanel({ runId }: { runId: string }) {
  const toast = useToast()
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    const body = { cancellation_id: `web:${runId}`, reason_code: "operator_requested" }
    const res = await safeApiPost<RunOperationResult>(`/api/v2/graph-runs/${encodeURIComponent(runId)}/cancel`, body)
    if (res.ok && res.data) {
      toast(res.data.message + (res.data.new_run_id ? ` → ${res.data.new_run_id}` : ""), "success")
    } else {
      toast(res.errorMessage ?? "Operation failed", "error")
    }
    setLoading(false)
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
      <div className="text-sm text-muted">Graph operation</div>
      <button
        type="submit"
        disabled={loading}
        className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-50"
      >
        {loading ? "Cancelling..." : "Cancel run"}
      </button>
    </form>
  )
}
