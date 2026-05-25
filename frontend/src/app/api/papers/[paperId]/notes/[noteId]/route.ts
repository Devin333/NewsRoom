import { cookies } from "next/headers"
import { NextRequest, NextResponse } from "next/server"
import { safeApiDelete, safeApiPatch } from "@/lib/api/server"
import { NEWSROOM_SESSION_COOKIE } from "@/lib/auth/session"

export const dynamic = "force-dynamic"

export async function PATCH(request: NextRequest, { params }: { params: { paperId: string; noteId: string } }) {
  const token = cookies().get(NEWSROOM_SESSION_COOKIE)?.value
  const body = await request.json().catch(() => ({}))
  const result = await safeApiPatch(
    `/api/v1/papers/${encodeURIComponent(params.paperId)}/notes/${encodeURIComponent(params.noteId)}`,
    body,
    {
      headers: token ? { "x-newsroom-session": token } : undefined,
    }
  )
  return noteResponse(result)
}

export async function DELETE(_request: NextRequest, { params }: { params: { paperId: string; noteId: string } }) {
  const token = cookies().get(NEWSROOM_SESSION_COOKIE)?.value
  const result = await safeApiDelete(
    `/api/v1/papers/${encodeURIComponent(params.paperId)}/notes/${encodeURIComponent(params.noteId)}`,
    {
      headers: token ? { "x-newsroom-session": token } : undefined,
    }
  )
  return noteResponse(result)
}

function noteResponse(result: Awaited<ReturnType<typeof safeApiPatch>>) {
  if (result.ok) {
    return NextResponse.json({ success: true, data: result.data })
  }
  const status =
    result.errorCode === "auth_session_required"
      ? 401
      : result.errorCode === "paper_reader_note_invalid"
        ? 400
        : result.errorCode === "paper_reader_note_not_found"
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
