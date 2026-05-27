import { notFound } from "next/navigation"
import { PaperDocumentReaderPage } from "@/components/papers/paper-reader"
import { safeApiGet } from "@/lib/api/server"
import type { PaperDocumentResponse } from "@/lib/paper-reader/types"

export const dynamic = "force-dynamic"

export default async function PaperDocumentReadRoute({ params }: { params: { slug: string } }) {
  const result = await safeApiGet<PaperDocumentResponse>(`/api/v1/papers/${encodeURIComponent(params.slug)}/document`)
  if (!result.ok) {
    notFound()
  }

  return <PaperDocumentReaderPage payload={result.data} locale="zh" />
}
