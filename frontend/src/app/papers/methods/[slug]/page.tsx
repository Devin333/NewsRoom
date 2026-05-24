import { notFound } from "next/navigation"
import { MethodDetailPageClient } from "@/app/papers/methods/[slug]/method-detail-page-client"
import { getMethodBySlug, paperMethods } from "@/lib/papers/mock-data"
import { getPublishedPapers } from "@/lib/papers/real-data"

export function generateStaticParams() {
  return paperMethods.map((method) => ({ slug: method.slug }))
}

export default function PapersMethodDetailPageRoute({ params }: { params: { slug: string } }) {
  const method = getMethodBySlug(params.slug)

  if (!method) {
    notFound()
  }

  return <MethodDetailPageClient method={method} papers={getPublishedPapers()} />
}
