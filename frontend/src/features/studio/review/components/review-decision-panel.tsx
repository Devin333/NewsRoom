"use client"

import { useState } from "react"
import { CheckCircle2, ShieldAlert, XCircle } from "lucide-react"
import { ErrorState } from "@/components/common/error-state"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { useReviewActions } from "@/features/studio/review/hooks/use-review-actions"
import { useI18n } from "@/lib/i18n/use-i18n"
import type { ReviewActionRequest, ReviewActionResult, ReviewDecisionAction, StudioReviewItem } from "@/types/review"

export type ReviewDecisionHandler = (request: ReviewActionRequest) => Promise<ReviewActionResult>

export function ReviewDecisionPanel({
  item,
  onSubmitAction
}: {
  item: StudioReviewItem
  onSubmitAction?: ReviewDecisionHandler
}) {
  const { locale, t } = useI18n()
  const { submitAction } = useReviewActions()
  const [error, setError] = useState<{ title?: string; message: string } | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [pendingRequest, setPendingRequest] = useState<ReviewActionRequest | null>(null)
  const disabledReason = actionDisabledReason(item, t)
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
      setSuccess(result.requestId ? t("studio.review.actionRecordedRequest", { requestId: result.requestId }) : t("studio.review.actionRecorded"))
      return
    }

    setError({
      title: result.errorCode,
      message: result.requestId ? `${result.errorMessage} Request ${result.requestId}.` : result.errorMessage
    })
  }

  function buildActionRequest(action: ReviewDecisionAction): ReviewActionRequest | { error: string } {
    if (disabledReason) return { error: disabledReason }
    return { item, action }
  }

  const showApprovalButtons = item.actionKind === "approval_decision"

  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <div className="mb-4 flex items-start gap-3">
        <ShieldAlert className="mt-0.5 size-5 text-primary" />
        <div>
          <h2 className="text-sm font-semibold text-foreground">{t("studio.review.decision")}</h2>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">{disabledReason ?? decisionSummary(item, t)}</p>
        </div>
      </div>

      {error ? <ErrorState title={error.title ?? t("studio.review.actionFailed")} message={error.message} /> : null}
      {success ? (
        <div className="mb-4 rounded-lg border border-success/30 bg-success/10 p-3 text-sm text-success">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="size-4" />
            <span>{success}</span>
          </div>
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap gap-2">
        {showApprovalButtons ? (
          <>
            <Button disabled={Boolean(disabledReason) || isSubmitting} onClick={() => beginAction("approve")} type="button">
              <CheckCircle2 className="size-4" />
              {t("studio.review.approve")}
            </Button>
            <Button disabled={Boolean(disabledReason) || isSubmitting} onClick={() => beginAction("reject")} type="button" variant="destructive">
              <XCircle className="size-4" />
              {t("studio.review.reject")}
            </Button>
          </>
        ) : null}
      </div>

      <Dialog open={Boolean(pendingRequest)} onOpenChange={(open) => !open && setPendingRequest(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("studio.review.confirmAction", { action: pendingRequest ? actionLabel(pendingRequest.action, locale) : t("common.actions") })}</DialogTitle>
            <DialogDescription>
              {t("studio.review.confirmDescription", { approvalId: item.approvalId })}
            </DialogDescription>
          </DialogHeader>
          <div className="mt-4 flex justify-end gap-2">
            <Button disabled={isSubmitting} onClick={() => setPendingRequest(null)} type="button" variant="outline">
              {t("common.cancel")}
            </Button>
            <Button disabled={isSubmitting} onClick={confirmAction} type="button">
              {t("studio.review.confirm", { action: pendingRequest ? actionLabel(pendingRequest.action, locale) : t("common.actions") })}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </section>
  )
}

function actionDisabledReason(item: StudioReviewItem, t: ReturnType<typeof useI18n>["t"]): string | undefined {
  if (item.actionDisabledReason) return item.actionDisabledReason
  if (item.actionKind === "none") return t("studio.review.noOperationAvailable")
  if (item.status !== "pending") return t("studio.review.alreadyDecided")
  return undefined
}

function decisionSummary(item: StudioReviewItem, t: ReturnType<typeof useI18n>["t"]): string {
  return t("studio.review.pendingSummary")
}

function actionLabel(action: ReviewDecisionAction, locale: "zh" | "en"): string {
  if (locale === "zh") {
    if (action === "approve") return "通过"
    if (action === "reject") return "驳回"
  }
  return action
}
