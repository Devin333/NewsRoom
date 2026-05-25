import { notFound } from "next/navigation"
import { MethodDetailPageClient } from "@/app/papers/methods/[slug]/method-detail-page-client"
import { getMethodBySlug, paperMethods } from "@/lib/papers/catalog"
import { getPublishedPapers, loadApiPaperMethods } from "@/lib/papers/real-data"

export function generateStaticParams() {
  return paperMethods.map((method) => ({ slug: method.slug }))
}

export default async function PapersMethodDetailPageRoute({ params }: { params: { slug: string } }) {
  const apiMethods = await loadApiPaperMethods()
  const method = apiMethods.find((item) => item.slug === params.slug) ?? getMethodBySlug(params.slug)

  if (!method) {
    notFound()
  }

  return (
    <MethodDetailPageClient
      method={method}
      papers={await getPublishedPapers()}
      fallbackNotice={apiMethods.length ? null : "Paper method API is unavailable; showing local catalog fallback."}
    />
  )
}
