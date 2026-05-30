"use client"

import { useState } from "react"
import { safeApiPost } from "@/lib/api-client"
import { useToast } from "@/components/common/Toast"
import type { RunOperationResult } from "@/lib/types"

const OPERATIONS = [
  { value: "cancel", label: "Cancel run" },
  { value: "rerun-from-step", label: "Rerun from step" },
  { value: "skip-step", label: "Skip step" },
  { value: "mark-blocked-resolved", label: "Mark blocked resolved" }
]

export function RunOperationPanel({ runId }: { runId: string }) {
  const toast = useToast()
  const [op, setOp] = useState(OPERATIONS[0].value)
  const [stepId, setStepId] = useState("")
  const [loading, setLoading] = useState(false)

  const needsStep = op === "rerun-from-step" || op === "skip-step"

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    const body = needsStep ? { step_id: stepId } : {}
    const res = await safeApiPost<RunOperationResult>(`/api/v1/runs/${runId}/operations/${op}`, body)
    if (res.ok && res.data) {
      toast(res.data.message + (res.data.new_run_id ? ` → ${res.data.new_run_id}` : ""), "success")
    } else {
      toast(res.errorMessage ?? "Operation failed", "error")
    }
    setLoading(false)
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
      <div className="flex-1 min-w-40">
        <label className="mb-1 block text-xs font-medium text-muted">Operation</label>
        <select
          value={op}
          onChange={(e) => setOp(e.target.value)}
          className="w-full rounded-md border border-line bg-white px-3 py-2 text-sm text-ink focus:border-accent focus:outline-none"
        >
          {OPERATIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </div>
      {needsStep && (
        <div className="flex-1 min-w-40">
          <label className="mb-1 block text-xs font-medium text-muted">Step ID</label>
          <input
            value={stepId}
            onChange={(e) => setStepId(e.target.value)}
            placeholder="step_id"
            className="w-full rounded-md border border-line bg-white px-3 py-2 text-sm text-ink placeholder:text-subtle focus:border-accent focus:outline-none"
          />
        </div>
      )}
      <button
        type="submit"
        disabled={loading || (needsStep && !stepId)}
        className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-50"
      >
        {loading ? "Running…" : "Execute"}
      </button>
    </form>
  )
}
