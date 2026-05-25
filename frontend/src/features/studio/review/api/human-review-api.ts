import type { ReviewActionRequest, ReviewActionResult } from "@/types/review"

type ApiEnvelope<T> = {
  success?: boolean
  data?: T | null
  error?: {
    code?: string
    message?: string
    detail?: unknown
    details?: unknown
    requestId?: string | null
    request_id?: string | null
  } | null
  request_id?: string | null
}

export async function submitReviewAction(request: ReviewActionRequest): Promise<ReviewActionResult> {
  if (request.action === "resolve_blocked_run") {
    if (!request.item.runId) {
      return {
        ok: false,
        errorCode: "missing_run_id",
        errorMessage: "run id is required to resolve a blocked run"
      }
    }
    return postReviewAction(`/api/v1/runs/${encodeURIComponent(request.item.runId)}/operations/mark-blocked-resolved`, {
      resolved_by: request.decidedBy,
      actor_id: request.decidedBy,
      reason: request.reason || undefined,
      resolution_type: "manual",
      metadata: {
        source: "studio-review",
        review_item_id: request.item.approvalId
      }
    })
  }

  const approvalPath = `/api/v1/approvals/${encodeURIComponent(request.item.approvalId)}/${request.action}`
  if (request.action === "modify") {
    return postReviewAction(approvalPath, {
      decided_by: request.decidedBy,
      reason: request.reason || undefined,
      modifications: request.modifications ?? {}
    })
  }

  return postReviewAction(approvalPath, {
    decided_by: request.decidedBy,
    reason: request.reason || undefined
  })
}

async function postReviewAction(path: string, body: unknown): Promise<ReviewActionResult> {
  try {
    const response = await fetch(path, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json"
      },
      body: JSON.stringify(body)
    })
    const requestIdFromHeader = response.headers.get("x-request-id") ?? undefined
    const payload = await parsePayload(response)
    const envelope = isEnvelope(payload) ? payload : undefined
    const requestId = requestIdFromHeader ?? envelope?.request_id ?? envelope?.error?.requestId ?? envelope?.error?.request_id ?? undefined

    if (!response.ok || envelope?.success === false) {
      const error = envelope?.error
      return {
        ok: false,
        errorCode: error?.code ?? `http_${response.status}`,
        errorMessage: error?.message ?? response.statusText ?? "Review action failed",
        requestId
      }
    }

    return {
      ok: true,
      requestId,
      data: envelope ? envelope.data : payload
    }
  } catch (error) {
    return {
      ok: false,
      errorCode: "request_failed",
      errorMessage: error instanceof Error ? error.message : "Review action failed"
    }
  }
}

async function parsePayload(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? ""
  if (contentType.includes("application/json")) return response.json()
  return response.text()
}

function isEnvelope(payload: unknown): payload is ApiEnvelope<unknown> {
  return typeof payload === "object" && payload !== null && "success" in payload
}
