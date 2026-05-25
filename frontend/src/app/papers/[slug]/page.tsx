import { notFound } from "next/navigation"
import { PaperReaderPage } from "@/components/papers/shared/paper-reader-page"
import { safeApiGet } from "@/lib/api/server"
import type { PaperReaderPayload } from "@/lib/papers/types"

type ReaderApiResponse = {
  reader: PaperReaderPayload
}

export const dynamic = "force-dynamic"

export default async function PaperReaderRoute({ params }: { params: { slug: string } }) {
  const result = await safeApiGet<ReaderApiResponse>(`/api/v1/papers/${encodeURIComponent(params.slug)}/reader?locale=en`)
  if (!result.ok) {
    notFound()
  }

  return <PaperReaderPage reader={result.data.reader} locale="en" />
}
