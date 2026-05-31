import { notFound } from "next/navigation"
import { PaperDocumentReaderPageClient } from "@/app/papers/[slug]/read/paper-document-reader-page-client"
import { loadPaperDocumentPayload } from "@/lib/paper-reader/server-loader"

export const dynamic = "force-dynamic"

export default async function PaperDocumentReadRoute({ params }: { params: { slug: string } }) {
  const payload = await loadPaperDocumentPayload(params.slug)
  if (!payload) {
    notFound()
  }

  return <PaperDocumentReaderPageClient payload={payload} />
}
