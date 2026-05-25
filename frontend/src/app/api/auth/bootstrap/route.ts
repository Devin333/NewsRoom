import { NextRequest, NextResponse } from "next/server"
import { safeApiPost } from "@/lib/api/server"
import { NEWSROOM_SESSION_COOKIE, sessionCookieOptions } from "@/lib/auth/session"

export const dynamic = "force-dynamic"

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => ({}))
  const result = await safeApiPost("/api/v1/auth/bootstrap", body)
  return authWriteResponse(result)
}

function authWriteResponse(result: Awaited<ReturnType<typeof safeApiPost>>) {
  if (result.ok) {
    const data = result.data as { session?: { sessionToken?: string } }
    const token = data.session?.sessionToken
    if (data.session) {
      delete data.session.sessionToken
    }
    const response = NextResponse.json({ success: true, data })
    if (token) {
      response.cookies.set(NEWSROOM_SESSION_COOKIE, token, sessionCookieOptions())
    }
    return response
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
    { status: result.errorCode === "auth_already_initialized" ? 409 : 400 }
  )
}
