import { NextResponse } from "next/server"
import { getPaperById } from "@/lib/papers/real-data"
import type { Paper } from "@/lib/papers/types"

type PublicPaperGuard =
  | {
      ok: true
      paper: Paper
    }
  | {
      ok: false
      response: NextResponse
    }

export async function requirePublicPaper(paperId: string): Promise<PublicPaperGuard> {
  const paper = await getPaperById(paperId)
  if (paper) {
    return { ok: true, paper }
  }
  return { ok: false, response: paperNotFoundResponse() }
}

export function paperNotFoundResponse() {
  return NextResponse.json(
    {
      success: false,
      error: {
        code: "paper_not_found",
        message: "Paper not found",
      },
    },
    { status: 404 },
  )
}

export function paperRouteErrorStatus(
  errorCode: string,
  {
    invalidCodes = [],
    notFoundCodes = [],
  }: {
    invalidCodes?: string[]
    notFoundCodes?: string[]
  } = {},
) {
  if (errorCode === "auth_session_required") {
    return 401
  }
  if (errorCode === "paper_not_found" || notFoundCodes.includes(errorCode)) {
    return 404
  }
  if (invalidCodes.includes(errorCode)) {
    return 400
  }
  return 502
}
