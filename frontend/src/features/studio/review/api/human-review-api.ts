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
  if (!request.item.runId || !request.item.nodeInstanceId) {
    return {
      ok: false,
      errorCode: "graph_wait_identity_required",
      errorMessage: "run id and node instance id are required for a Graph Wait decision"
    }
  }
  const approvalPath = `/api/v2/graph-runs/${encodeURIComponent(request.item.runId)}/waits/${encodeURIComponent(request.item.nodeInstanceId)}/approval`
  return postReviewAction(approvalPath, {
    approval_id: request.item.approvalId,
    approved: request.action === "approve"
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
