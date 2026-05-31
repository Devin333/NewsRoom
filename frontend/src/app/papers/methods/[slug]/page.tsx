import { notFound } from "next/navigation"
import { MethodDetailPageClient } from "@/app/papers/methods/[slug]/method-detail-page-client"
import { getMethodBySlug, paperMethods } from "@/lib/papers/catalog"
import { getPaperMethodsResult, getPublishedPapers } from "@/lib/papers/real-data"
import { decodePaperRouteSlug } from "@/lib/papers/routes"

export function generateStaticParams() {
  return paperMethods.map((method) => ({ slug: method.slug }))
}

export default async function PapersMethodDetailPageRoute({ params }: { params: { slug: string } }) {
  const slug = decodePaperRouteSlug(params.slug)
  const result = await getPaperMethodsResult()
  const method = result.items.find((item) => item.slug === slug) ?? getMethodBySlug(slug)

  if (!method) {
    notFound()
  }

  return (
    <MethodDetailPageClient
      method={method}
      papers={await getPublishedPapers()}
      fallbackNotice={result.source === "backend" ? null : result.notices[0] ?? null}
    />
  )
}
