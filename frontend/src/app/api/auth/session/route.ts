import { cookies } from "next/headers"
import { NextResponse } from "next/server"
import { safeApiGet } from "@/lib/api/server"
import { NEWSROOM_SESSION_COOKIE } from "@/lib/auth/session"

export const dynamic = "force-dynamic"

export async function GET() {
  const token = cookies().get(NEWSROOM_SESSION_COOKIE)?.value
  const result = await safeApiGet("/api/v1/auth/session", {
    headers: token ? { "x-newsroom-session": token } : undefined,
  })
  if (result.ok) {
    const response = NextResponse.json({ success: true, data: result.data })
    const data = result.data as { session?: unknown } | undefined
    if (token && !data?.session) {
      response.cookies.delete(NEWSROOM_SESSION_COOKIE)
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
    { status: 502 }
  )
}
