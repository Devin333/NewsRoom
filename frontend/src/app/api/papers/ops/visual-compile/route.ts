import { NextRequest, NextResponse } from "next/server"
import { safeApiPost } from "@/lib/api/server"

export const dynamic = "force-dynamic"
export const runtime = "nodejs"

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => ({}))
  const result = await safeApiPost("/api/v1/papers/ops/visual-compile/trigger", body)
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
    { status: result.errorCode === "paper_visual_compile_backfill_invalid" ? 400 : 502 },
  )
}
