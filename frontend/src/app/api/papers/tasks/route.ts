import { NextResponse } from "next/server"
import { safeApiGet } from "@/lib/api/server"

export const dynamic = "force-dynamic"

export async function GET() {
  const result = await safeApiGet("/api/v1/papers/tasks")
  if (result.ok) {
    return NextResponse.json({ success: true, data: result.data })
  }
  return NextResponse.json(
    {
      success: false,
      error: {
        code: result.errorCode,
        message: result.errorMessage,
        requestId: result.requestId,
      },
    },
    { status: result.errorCode === "papers_cache_not_found" ? 404 : 502 }
  )
}
