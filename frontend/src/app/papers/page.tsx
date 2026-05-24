import { PapersPageClient } from "@/app/papers/papers-page-client"
import { getPublishedPapers } from "@/lib/papers/real-data"

export const dynamic = "force-dynamic"

export default async function PapersPageRoute() {
  const papers = await getPublishedPapers()

  return <PapersPageClient papers={papers} />
}
