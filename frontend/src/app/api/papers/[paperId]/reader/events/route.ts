import { cookies } from "next/headers"
import { NextRequest, NextResponse } from "next/server"
import { safeApiPost } from "@/lib/api/server"
import { NEWSROOM_SESSION_COOKIE } from "@/lib/auth/session"

export const dynamic = "force-dynamic"

export async function POST(request: NextRequest, { params }: { params: { paperId: string } }) {
  const token = cookies().get(NEWSROOM_SESSION_COOKIE)?.value
  const body = await request.json().catch(() => ({}))
  const result = await safeApiPost(`/api/v1/papers/${encodeURIComponent(params.paperId)}/reader/events`, body, {
    headers: token ? { "x-newsroom-session": token } : undefined,
  })
  return readerInteractionResponse(result)
}

function readerInteractionResponse(result: Awaited<ReturnType<typeof safeApiPost>>) {
  if (result.ok) {
    return NextResponse.json({ success: true, data: result.data })
  }
  const status =
    result.errorCode === "auth_session_required"
      ? 401
      : result.errorCode === "paper_reader_event_invalid"
        ? 400
        : 502
  return NextResponse.json(
    {
      success: false,
      error: {
        code: result.errorCode,
        message: result.errorMessage,
        requestId: result.requestId,
      },
    },
    { status }
  )
}
