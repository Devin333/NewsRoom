"use client"

import { useState } from "react"
import { CheckCircle2, ShieldAlert, XCircle } from "lucide-react"
import { ErrorState } from "@/components/common/error-state"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { useReviewActions } from "@/features/studio/review/hooks/use-review-actions"
import type { ReviewActionRequest, ReviewActionResult, ReviewDecisionAction, StudioReviewItem } from "@/types/review"

export type ReviewDecisionHandler = (request: ReviewActionRequest) => Promise<ReviewActionResult>

export function ReviewDecisionPanel({
  item,
  onSubmitAction
}: {
  item: StudioReviewItem
  onSubmitAction?: ReviewDecisionHandler
}) {
  const { submitAction } = useReviewActions()
  const [decidedBy, setDecidedBy] = useState("")
  const [reason, setReason] = useState("")
  const [modifications, setModifications] = useState("{\n  \n}")
  const [error, setError] = useState<{ title?: string; message: string } | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [pendingRequest, setPendingRequest] = useState<ReviewActionRequest | null>(null)
  const disabledReason = actionDisabledReason(item)
  const handler = onSubmitAction ?? submitAction

  function beginAction(action: ReviewDecisionAction) {
    setError(null)
    setSuccess(null)
    const request = buildActionRequest(action)
    if ("error" in request) {
      setError({ message: request.error })
      return
    }
    setPendingRequest(request)
  }

  async function confirmAction() {
    if (!pendingRequest) return
    setIsSubmitting(true)
    setError(null)
    setSuccess(null)
    const result = await handler(pendingRequest)
    setIsSubmitting(false)
    setPendingRequest(null)

    if (result.ok) {
      setSuccess(result.requestId ? `Action recorded. Request ${result.requestId}.` : "Action recorded.")
      return
    }

    setError({
      title: result.errorCode,
      message: result.requestId ? `${result.errorMessage} Request ${result.requestId}.` : result.errorMessage
    })
  }

  function buildActionRequest(action: ReviewDecisionAction): ReviewActionRequest | { error: string } {
    const actor = decidedBy.trim()
    if (!actor) return { error: "decided_by is required." }
    if (disabledReason) return { error: disabledReason }

    if (action === "resolve_blocked_run") {
      if (!item.runId) return { error: "run id is required." }
      return {
        item,
        action,
        decidedBy: actor,
        reason: reason.trim() || undefined
      }
    }

    if (action === "modify") {
      const parsed = parseModifications(modifications)
      if ("error" in parsed) return parsed
      return {
        item,
        action,
        decidedBy: actor,
        reason: reason.trim() || undefined,
        modifications: parsed.value
      }
    }

    return {
      item,
      action,
      decidedBy: actor,
      reason: reason.trim() || undefined
    }
  }

  const showApprovalButtons = item.actionKind !== "resolve_blocked_run"
  const showResolveButton = item.actionKind === "resolve_blocked_run"

  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <div className="mb-4 flex items-start gap-3">
        <ShieldAlert className="mt-0.5 size-5 text-primary" />
        <div>
          <h2 className="text-sm font-semibold text-foreground">Decision</h2>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">{disabledReason ?? decisionSummary(item)}</p>
        </div>
      </div>

      {error ? <ErrorState title={error.title ?? "Review action failed"} message={error.message} /> : null}
      {success ? (
        <div className="mb-4 rounded-lg border border-success/30 bg-success/10 p-3 text-sm text-success">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="size-4" />
            <span>{success}</span>
          </div>
        </div>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2">
        <label className="space-y-1 text-sm font-medium text-foreground">
          <span>decided_by</span>
          <Input
            aria-label="decided_by"
            disabled={Boolean(disabledReason) || isSubmitting}
            onChange={(event) => setDecidedBy(event.target.value)}
            placeholder="ops-reviewer"
            value={decidedBy}
          />
        </label>
        <label className="space-y-1 text-sm font-medium text-foreground md:col-span-2">
          <span>Reason</span>
          <textarea
            aria-label="reason"
            className="min-h-20 w-full rounded-md border border-input bg-card px-3 py-2 text-sm text-foreground shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
            disabled={Boolean(disabledReason) || isSubmitting}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Optional decision note"
            value={reason}
          />
        </label>
        {showApprovalButtons ? (
          <label className="space-y-1 text-sm font-medium text-foreground md:col-span-2">
            <span>Modify payload</span>
            <textarea
              aria-label="modifications JSON"
              className="min-h-28 w-full rounded-md border border-input bg-card px-3 py-2 font-mono text-sm text-foreground shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
              disabled={Boolean(disabledReason) || isSubmitting}
              onChange={(event) => setModifications(event.target.value)}
              value={modifications}
            />
          </label>
        ) : null}
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {showApprovalButtons ? (
          <>
            <Button disabled={Boolean(disabledReason) || isSubmitting} onClick={() => beginAction("approve")} type="button">
              <CheckCircle2 className="size-4" />
              Approve
            </Button>
            <Button disabled={Boolean(disabledReason) || isSubmitting} onClick={() => beginAction("reject")} type="button" variant="destructive">
              <XCircle className="size-4" />
              Reject
            </Button>
            <Button disabled={Boolean(disabledReason) || isSubmitting} onClick={() => beginAction("modify")} type="button" variant="outline">
              Modify
            </Button>
          </>
        ) : null}
        {showResolveButton ? (
          <Button disabled={Boolean(disabledReason) || isSubmitting} onClick={() => beginAction("resolve_blocked_run")} type="button">
            <CheckCircle2 className="size-4" />
            Mark resolved
          </Button>
        ) : null}
      </div>

      <Dialog open={Boolean(pendingRequest)} onOpenChange={(open) => !open && setPendingRequest(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Confirm {pendingRequest ? actionLabel(pendingRequest.action) : "action"}</DialogTitle>
            <DialogDescription>
              This will submit a real operation for {item.approvalId} as {pendingRequest?.decidedBy}.
            </DialogDescription>
          </DialogHeader>
          <div className="mt-4 flex justify-end gap-2">
            <Button disabled={isSubmitting} onClick={() => setPendingRequest(null)} type="button" variant="outline">
              Cancel
            </Button>
            <Button disabled={isSubmitting} onClick={confirmAction} type="button">
              Confirm {pendingRequest ? actionLabel(pendingRequest.action) : "action"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </section>
  )
}

function parseModifications(value: string): { value: Record<string, unknown> } | { error: string } {
  let parsed: unknown
  try {
    parsed = JSON.parse(value)
  } catch {
    return { error: "modifications must be valid JSON." }
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    return { error: "modifications must be a JSON object." }
  }
  const record = parsed as Record<string, unknown>
  if (!Object.keys(record).length) return { error: "modifications are required for modify decisions." }
  return { value: record }
}

function actionDisabledReason(item: StudioReviewItem): string | undefined {
  if (item.actionDisabledReason) return item.actionDisabledReason
  if (item.actionKind === "resolve_blocked_run") {
    return item.runId ? undefined : "Blocked run resolution requires a run id."
  }
  if (item.actionKind === "none") return "No real operation is available for this review item."
  if (item.status !== "pending") return "This approval already has a recorded decision."
  return undefined
}

function decisionSummary(item: StudioReviewItem): string {
  if (item.actionKind === "resolve_blocked_run") return "Resolve the blocked run after confirming the issue is cleared."
  return "Approve, reject, or modify the pending approval."
}

function actionLabel(action: ReviewDecisionAction): string {
  if (action === "resolve_blocked_run") return "resolve"
  return action
}
