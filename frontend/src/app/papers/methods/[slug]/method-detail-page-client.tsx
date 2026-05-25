"use client"

import { MethodDetailPage } from "@/components/papers/methods/method-detail-page"
import type { Paper, PaperMethod } from "@/lib/papers/types"
import { useUiStore } from "@/stores/ui-store"

export function MethodDetailPageClient({
  method,
  papers,
  fallbackNotice
}: {
  method: PaperMethod
  papers: Paper[]
  fallbackNotice?: string | null
}) {
  const locale = useUiStore((state) => state.locale)

  return <MethodDetailPage method={method} locale={locale} papers={papers} fallbackNotice={fallbackNotice} />
}
