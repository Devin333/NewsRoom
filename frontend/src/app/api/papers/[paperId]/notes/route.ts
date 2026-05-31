import { cookies } from "next/headers"
import { NextRequest, NextResponse } from "next/server"
import { safeApiGet, safeApiPost } from "@/lib/api/server"
import { NEWSROOM_SESSION_COOKIE } from "@/lib/auth/session"
import { requirePublicPaper } from "@/lib/papers/public-route-guard"

export const dynamic = "force-dynamic"

export async function GET(_request: NextRequest, { params }: { params: { paperId: string } }) {
  const guard = await requirePublicPaper(params.paperId)
  if (!guard.ok) {
    return guard.response
  }

  const token = cookies().get(NEWSROOM_SESSION_COOKIE)?.value
  const result = await safeApiGet(`/api/v1/papers/${encodeURIComponent(guard.paper.id)}/notes`, {
    headers: token ? { "x-newsroom-session": token } : undefined,
  })
  return notesResponse(result)
}

export async function POST(request: NextRequest, { params }: { params: { paperId: string } }) {
  const guard = await requirePublicPaper(params.paperId)
  if (!guard.ok) {
    return guard.response
  }

  const token = cookies().get(NEWSROOM_SESSION_COOKIE)?.value
  const body = await request.json().catch(() => ({}))
  const result = await safeApiPost(`/api/v1/papers/${encodeURIComponent(guard.paper.id)}/notes`, body, {
    headers: token ? { "x-newsroom-session": token } : undefined,
  })
  return notesResponse(result)
}

function notesResponse(result: Awaited<ReturnType<typeof safeApiGet>>) {
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
    { status: result.errorCode === "auth_session_required" ? 401 : result.errorCode === "paper_reader_note_invalid" ? 400 : 502 }
  )
}
