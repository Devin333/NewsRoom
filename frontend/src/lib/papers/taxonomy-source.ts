import { translate } from "@/lib/i18n"
import { formatPaperDate } from "@/lib/papers/format"
import type { Locale } from "@/lib/papers/types"

export function taxonomySourceDescription(locale: Locale, paperCount: number, latestPaperTime?: number) {
  if (latestPaperTime && Number.isFinite(latestPaperTime)) {
    return translate(locale, "papers.taxonomy.sourceUpdated", {
      count: paperCount,
      date: formatPaperDate(new Date(latestPaperTime).toISOString(), locale)
    })
  }

  return translate(locale, "papers.taxonomy.source", { count: paperCount })
}
