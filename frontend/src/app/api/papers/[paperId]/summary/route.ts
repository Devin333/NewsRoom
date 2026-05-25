import { NextRequest, NextResponse } from "next/server"
import { safeApiPost } from "@/lib/api/server"

export const dynamic = "force-dynamic"

export async function POST(request: NextRequest, { params }: { params: { paperId: string } }) {
  const locale = request.nextUrl.searchParams.get("locale") ?? "en"
  const refresh = request.nextUrl.searchParams.get("refresh") === "true"
  const searchParams = new URLSearchParams({ locale })
  if (refresh) {
    searchParams.set("refresh", "true")
  }
  const result = await safeApiPost(
    `/api/v1/papers/${encodeURIComponent(params.paperId)}/summary?${searchParams.toString()}`
  )
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
        retryable: result.errorCode === "paper_summary_unavailable",
      },
    },
    { status: result.errorCode === "paper_summary_unavailable" ? 503 : 502 }
  )
}
