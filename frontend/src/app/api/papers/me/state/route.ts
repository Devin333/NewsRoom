import { cookies } from "next/headers"
import { NextRequest, NextResponse } from "next/server"
import { safeApiGet } from "@/lib/api/server"
import { NEWSROOM_SESSION_COOKIE } from "@/lib/auth/session"

export const dynamic = "force-dynamic"

export async function GET(request: NextRequest) {
  const token = cookies().get(NEWSROOM_SESSION_COOKIE)?.value
  const paperIds = request.nextUrl.searchParams.get("paperIds")
  const query = paperIds ? `?paperIds=${encodeURIComponent(paperIds)}` : ""
  const result = await safeApiGet(`/api/v1/papers/me/state${query}`, {
    headers: token ? { "x-newsroom-session": token } : undefined,
  })
  return stateResponse(result)
}

function stateResponse(result: Awaited<ReturnType<typeof safeApiGet>>) {
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
    { status: result.errorCode === "auth_session_required" ? 401 : 502 }
  )
}
