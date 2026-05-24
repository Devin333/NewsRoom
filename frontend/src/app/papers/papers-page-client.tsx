"use client"

import { TrendingPapersPage } from "@/components/papers/trending-papers-page"
import type { Paper } from "@/lib/papers/types"
import { useUiStore } from "@/stores/ui-store"

export function PapersPageClient({ papers }: { papers: Paper[] }) {
  const locale = useUiStore((state) => state.locale)

  return <TrendingPapersPage locale={locale} papers={papers} />
}
