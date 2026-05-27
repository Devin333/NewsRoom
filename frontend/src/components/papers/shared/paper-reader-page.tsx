"use client"

import { OpenReaderPage } from "@/components/papers/open-reader"
import type { Locale, PaperReaderPayload } from "@/lib/papers/types"

export function PaperReaderPage({ reader, locale }: { reader: PaperReaderPayload; locale: Locale }) {
  return <OpenReaderPage reader={reader} locale={locale} />
}
