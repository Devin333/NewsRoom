import { NextRequest, NextResponse } from "next/server"
import { safeApiGet, safeApiPost } from "@/lib/api/server"

export const dynamic = "force-dynamic"
export const runtime = "nodejs"

export async function GET(request: NextRequest) {
  const limit = request.nextUrl.searchParams.get("limit") ?? "20"
  const result = await safeApiGet(`/api/v1/papers/ops/ingest?limit=${encodeURIComponent(limit)}`)
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

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => ({}))
  const result = await safeApiPost("/api/v1/papers/ops/ingest/trigger", body)
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
