import { notFound } from "next/navigation"
import { PaperDocumentReaderPage } from "@/components/papers/paper-reader"
import { loadPaperDocumentPayload } from "@/lib/paper-reader/server-loader"

export const dynamic = "force-dynamic"

export default async function PaperDocumentReadRoute({ params }: { params: { slug: string } }) {
  const payload = await loadPaperDocumentPayload(params.slug)
  if (!payload) {
    notFound()
  }

  return <PaperDocumentReaderPage payload={payload} locale="zh" />
}
