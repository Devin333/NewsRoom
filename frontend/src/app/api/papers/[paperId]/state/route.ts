import { cookies } from "next/headers"
import { NextRequest, NextResponse } from "next/server"
import { safeApiGet, safeApiPatch } from "@/lib/api/server"
import { NEWSROOM_SESSION_COOKIE } from "@/lib/auth/session"

export const dynamic = "force-dynamic"

export async function GET(_request: NextRequest, { params }: { params: { paperId: string } }) {
  const token = cookies().get(NEWSROOM_SESSION_COOKIE)?.value
  const result = await safeApiGet(`/api/v1/papers/${encodeURIComponent(params.paperId)}/state`, {
    headers: token ? { "x-newsroom-session": token } : undefined,
  })
  return stateResponse(result)
}

export async function PATCH(request: NextRequest, { params }: { params: { paperId: string } }) {
  const token = cookies().get(NEWSROOM_SESSION_COOKIE)?.value
  const body = await request.json().catch(() => ({}))
  const result = await safeApiPatch(`/api/v1/papers/${encodeURIComponent(params.paperId)}/state`, body, {
    headers: token ? { "x-newsroom-session": token } : undefined,
  })
  return stateResponse(result)
}

function stateResponse(result: Awaited<ReturnType<typeof safeApiGet>>) {
  if (result.ok) {
    return NextResponse.json({ success: true, data: result.data })
  }
  const status = result.errorCode === "auth_session_required" ? 401 : result.errorCode === "paper_state_invalid" ? 400 : 502
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
