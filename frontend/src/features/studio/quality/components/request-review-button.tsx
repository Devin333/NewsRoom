"use client"

import { useState, useTransition } from "react"
import { Send } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import type {
  StudioQualityDataState,
  StudioRequestReviewAction,
  StudioRequestReviewPayload,
  StudioRequestReviewResult
} from "@/types/quality"

export function RequestReviewButton({
  reportId,
  dataState,
  requestReviewAction
}: {
  reportId: string
  dataState: StudioQualityDataState
  requestReviewAction: StudioRequestReviewAction
}) {
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState("")
  const [requestedBy, setRequestedBy] = useState("")
  const [result, setResult] = useState<StudioRequestReviewResult>()
  const [validation, setValidation] = useState<string>()
  const [isPending, startTransition] = useTransition()
  const disabled = dataState === "fallback"

  function submit() {
    const trimmedReason = reason.trim()
    if (!trimmedReason) {
      setValidation("Reason is required.")
      return
    }

    const payload: StudioRequestReviewPayload = {
      reason: trimmedReason,
      ...(requestedBy.trim() ? { requested_by: requestedBy.trim() } : {}),
      metadata: { source: "studio_quality_gate" }
    }

    setValidation(undefined)
    startTransition(async () => {
      const response = await requestReviewAction(reportId, payload)
      setResult(response)
      if (response.ok) {
        setReason("")
        setRequestedBy("")
      }
    })
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button disabled={disabled} title={disabled ? "Live API data is required to request review." : undefined}>
          <Send className="size-4" />
          Request review
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Request human review</DialogTitle>
          <DialogDescription>Submit a governed review request for this report quality gate.</DialogDescription>
        </DialogHeader>
        {disabled ? (
          <p className="rounded-md border border-warning/30 bg-warning/10 p-3 text-sm text-warning">
            Request Review is disabled while this page is using fallback data.
          </p>
        ) : null}
        <div className="space-y-4">
          <label className="block space-y-1.5">
            <span className="text-sm font-medium text-foreground">Reason</span>
            <textarea
              className="min-h-28 w-full rounded-md border border-input bg-card px-3 py-2 text-sm text-foreground shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Explain why this report needs human review."
              disabled={disabled || isPending}
            />
          </label>
          <label className="block space-y-1.5">
            <span className="text-sm font-medium text-foreground">Requested by</span>
            <Input
              value={requestedBy}
              onChange={(event) => setRequestedBy(event.target.value)}
              placeholder="operator@example.com"
              disabled={disabled || isPending}
            />
          </label>
          {validation ? <p className="text-sm text-danger">{validation}</p> : null}
          {result ? (
            result.ok ? (
              <div className="rounded-md border border-success/30 bg-success/10 p-3 text-sm text-success">
                <p>{result.message}</p>
                {result.approvalId ? <p className="mt-1 font-mono">Approval: {result.approvalId}</p> : null}
                {result.requestId ? <p className="mt-1 font-mono">RequestId: {result.requestId}</p> : null}
              </div>
            ) : (
              <div className="rounded-md border border-danger/30 bg-danger/10 p-3 text-sm text-danger">
                <p>{result.errorMessage}</p>
                {result.requestId ? <p className="mt-1 font-mono">RequestId: {result.requestId}</p> : null}
              </div>
            )
          ) : null}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => setOpen(false)} disabled={isPending}>
              Close
            </Button>
            <Button type="button" onClick={submit} disabled={disabled || isPending}>
              <Send className="size-4" />
              {isPending ? "Submitting" : "Submit"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
