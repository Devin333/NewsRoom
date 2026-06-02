import { NextRequest, NextResponse } from "next/server"
import { safeApiGet } from "@/lib/api/server"
import { requirePaperOpsSession } from "@/lib/papers/ops-route-guard"

export const dynamic = "force-dynamic"
export const runtime = "nodejs"

export async function GET(request: NextRequest) {
  const guard = await requirePaperOpsSession()
  if (guard) {
    return guard
  }

  const windowHours = request.nextUrl.searchParams.get("windowHours") ?? "24"
  const result = await safeApiGet(`/api/v1/papers/ops/stats?windowHours=${encodeURIComponent(windowHours)}`)
  if (result.ok) {
    return NextResponse.json({ success: true, data: result.data, request_id: null })
  }
  return NextResponse.json(
    {
      success: false,
      error: {
        code: result.errorCode,
        message: result.errorMessage,
        requestId: result.requestId,
      },
      request_id: result.requestId ?? null,
    },
    { status: 502 }
  )
}
