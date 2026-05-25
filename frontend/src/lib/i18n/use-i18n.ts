"use client"

import { useMemo } from "react"
import {
  createTranslator,
  formatDataState,
  formatDateTime,
  formatStatus,
  type Translator
} from "@/lib/i18n"
import { useUiStore } from "@/stores/ui-store"

export type I18nHelpers = {
  locale: "zh" | "en"
  t: Translator
  status: (value: string | null | undefined) => string
  dataState: (value: string | null | undefined) => string
  dateTime: (value: string | number | Date | null | undefined) => string
}

export function useI18n(): I18nHelpers {
  const locale = useUiStore((state) => state.locale)

  return useMemo(
    () => ({
      locale,
      t: createTranslator(locale),
      status: (value: string | null | undefined) => formatStatus(locale, value),
      dataState: (value: string | null | undefined) => formatDataState(locale, value),
      dateTime: (value: string | number | Date | null | undefined) => formatDateTime(locale, value)
    }),
    [locale]
  )
}
