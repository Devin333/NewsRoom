import { PapersPageClient } from "@/app/papers/papers-page-client"
import { getPublishedPapers } from "@/lib/papers/real-data"

export const dynamic = "force-dynamic"

export default function PapersPageRoute() {
  const papers = getPublishedPapers()

  return <PapersPageClient papers={papers} />
}
