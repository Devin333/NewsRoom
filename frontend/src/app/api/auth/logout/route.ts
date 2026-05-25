import { cookies } from "next/headers"
import { NextResponse } from "next/server"
import { safeApiPost } from "@/lib/api/server"
import { NEWSROOM_SESSION_COOKIE } from "@/lib/auth/session"

export const dynamic = "force-dynamic"

export async function POST() {
  const token = cookies().get(NEWSROOM_SESSION_COOKIE)?.value
  const result = await safeApiPost(
    "/api/v1/auth/logout",
    {},
    { headers: token ? { "x-newsroom-session": token } : undefined }
  )
  const response = NextResponse.json(
    result.ok
      ? { success: true, data: result.data }
      : {
          success: false,
          error: {
            code: result.errorCode,
            message: result.errorMessage,
            requestId: result.requestId,
          },
        },
    { status: result.ok ? 200 : 502 }
  )
  response.cookies.delete(NEWSROOM_SESSION_COOKIE)
  return response
}
