import { cookies } from "next/headers"
import { NextRequest, NextResponse } from "next/server"
import { safeApiPatch } from "@/lib/api/server"
import { NEWSROOM_SESSION_COOKIE } from "@/lib/auth/session"

export const dynamic = "force-dynamic"

export async function PATCH(
  request: NextRequest,
  { params }: { params: { paperId: string; selectionId: string } }
) {
  const token = cookies().get(NEWSROOM_SESSION_COOKIE)?.value
  const body = await request.json().catch(() => ({}))
  const result = await safeApiPatch(
    `/api/v1/papers/${encodeURIComponent(params.paperId)}/reader/selections/${encodeURIComponent(params.selectionId)}`,
    body,
    {
      headers: token ? { "x-newsroom-session": token } : undefined,
    }
  )
  return readerSelectionResponse(result)
}

function readerSelectionResponse(result: Awaited<ReturnType<typeof safeApiPatch>>) {
  if (result.ok) {
    return NextResponse.json({ success: true, data: result.data })
  }
  const status =
    result.errorCode === "auth_session_required"
      ? 401
      : result.errorCode === "paper_reader_selection_invalid"
        ? 400
        : result.errorCode === "paper_reader_selection_not_found"
          ? 404
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
