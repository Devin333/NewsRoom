import { NextRequest, NextResponse } from "next/server"
import { getPaperById } from "@/lib/papers/real-data"

export const dynamic = "force-dynamic"

export async function GET(_request: NextRequest, { params }: { params: { paperId: string } }) {
  const paper = await getPaperById(params.paperId)
  if (paper) {
    return NextResponse.json({ success: true, data: { paper } })
  }
  return NextResponse.json(
    {
      success: false,
      error: {
        code: "paper_not_found",
        message: "Paper not found",
      },
    },
    { status: 404 }
  )
}
