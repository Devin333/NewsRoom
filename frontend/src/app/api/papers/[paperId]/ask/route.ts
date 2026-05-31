import { NextRequest, NextResponse } from "next/server"
import { safeApiPost } from "@/lib/api/server"
import { requirePublicPaper } from "@/lib/papers/public-route-guard"

export const dynamic = "force-dynamic"

export async function POST(request: NextRequest, { params }: { params: { paperId: string } }) {
  const guard = await requirePublicPaper(params.paperId)
  if (!guard.ok) {
    return guard.response
  }

  const body = await request.json().catch(() => ({}))
  const locale = typeof body?.locale === "string" ? body.locale : "en"
  const question = typeof body?.question === "string" ? body.question : ""
  const result = await safeApiPost(`/api/v1/papers/${encodeURIComponent(guard.paper.id)}/ask`, {
    question,
    locale,
  })
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
        retryable: result.errorCode !== "paper_question_invalid" && result.errorCode !== "paper_not_found",
      },
    },
    { status: result.errorCode === "paper_not_found" ? 404 : result.errorCode === "paper_question_invalid" ? 400 : 502 }
  )
}
