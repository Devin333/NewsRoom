"use client"

import { useState, useTransition } from "react"
import { useRouter } from "next/navigation"
import { ErrorState } from "@/components/common/ErrorState"
import { safeApiPost } from "@/lib/api-client"
import type { RunOperationResult } from "@/lib/types"

type OperationKey = "cancel" | "rerun-from-step" | "skip-step" | "mark-blocked-resolved"

const operationLabels: Record<OperationKey, string> = {
  cancel: "Cancel run",
  "rerun-from-step": "Rerun from step",
  "skip-step": "Skip step",
  "mark-blocked-resolved": "Mark blocked resolved"
}

export function RunOperationPanel({ runId }: { runId: string }) {
  const router = useRouter()
  const [operation, setOperation] = useState<OperationKey>("cancel")
  const [reason, setReason] = useState("")
  const [stepId, setStepId] = useState("")
  const [result, setResult] = useState<RunOperationResult | null>(null)
  const [error, setError] = useState<{ message?: string; requestId?: string } | null>(null)
  const [isPending, startTransition] = useTransition()

  async function submit() {
    const label = operationLabels[operation]
    if (!window.confirm(`${label}?`)) {
      return
    }
    setError(null)
    setResult(null)
    const body = buildBody(operation, reason, stepId)
    const response = await safeApiPost<RunOperationResult>(
      `/api/v1/runs/${encodeURIComponent(runId)}/operations/${operation}`,
      body
    )
    if (response.ok && response.data) {
      setResult(response.data)
      startTransition(() => router.refresh())
    } else {
      setError({ message: response.errorMessage, requestId: response.requestId })
    }
  }

  const needsStep = operation === "rerun-from-step" || operation === "skip-step"

  return (
    <section className="rounded-lg border border-line bg-white p-4">
      <h2 className="text-base font-semibold text-ink">Operations</h2>
      <div className="mt-4 grid gap-3">
        <label className="grid gap-1 text-sm">
          <span className="font-medium text-muted">Operation</span>
          <select
            className="h-10 rounded-md border border-line bg-white px-3 text-ink"
            value={operation}
            onChange={(event) => setOperation(event.target.value as OperationKey)}
          >
            {Object.entries(operationLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        {needsStep ? (
          <label className="grid gap-1 text-sm">
            <span className="font-medium text-muted">Step ID</span>
            <input
              className="h-10 rounded-md border border-line px-3 text-ink"
              value={stepId}
              onChange={(event) => setStepId(event.target.value)}
            />
          </label>
        ) : null}
        <label className="grid gap-1 text-sm">
          <span className="font-medium text-muted">Reason</span>
          <input
            className="h-10 rounded-md border border-line px-3 text-ink"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </label>
        <button
          className="h-10 rounded-md bg-accent px-4 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-60"
          disabled={isPending || (needsStep && !stepId)}
          onClick={submit}
          type="button"
        >
          Apply
        </button>
      </div>
      {result ? (
        <div className="mt-3 rounded-md border border-good/30 bg-good/10 p-3 text-sm text-good">
          <p>
            {result.operation_type} {result.status}: {result.message}
          </p>
          {result.new_run_id ? <p className="mt-1 font-mono text-xs">new_run_id={result.new_run_id}</p> : null}
          {result.details ? (
            <pre className="mt-2 whitespace-pre-wrap break-words text-xs text-ink">{JSON.stringify(result.details, null, 2)}</pre>
          ) : null}
        </div>
      ) : null}
      {error ? <div className="mt-3"><ErrorState message={error.message} requestId={error.requestId} /></div> : null}
    </section>
  )
}

function buildBody(operation: OperationKey, reason: string, stepId: string) {
  if (operation === "rerun-from-step") {
    return { step_id: stepId }
  }
  if (operation === "skip-step") {
    return { step_id: stepId, reason: reason || null }
  }
  if (operation === "mark-blocked-resolved") {
    return { reason: reason || null, resolution_type: "manual" }
  }
  return { reason: reason || null }
}
