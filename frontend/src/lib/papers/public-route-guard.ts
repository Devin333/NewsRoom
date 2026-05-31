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
