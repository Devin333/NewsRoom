import type { LocaleMode } from "@/stores/ui-store"
import { translations, type TranslationDictionary, type TranslationKey } from "@/lib/i18n/translations"

export type { TranslationDictionary, TranslationKey }

export type TranslationParams = Record<string, string | number | boolean | null | undefined>
export type Translator = (key: TranslationKey | string, params?: TranslationParams) => string

export function normalizeLocale(locale: string | null | undefined): LocaleMode {
  return locale === "en" ? "en" : "zh"
}

export function translate(locale: LocaleMode, key: TranslationKey | string, params?: TranslationParams): string {
  const dictionary = translations[locale]
  const fallbackDictionary = translations.en
  const template =
    dictionary[key as TranslationKey] ?? fallbackDictionary[key as TranslationKey] ?? key

  return interpolate(template, params)
}

export function createTranslator(locale: LocaleMode): Translator {
  return (key, params) => translate(locale, key, params)
}

export function interpolate(template: string, params?: TranslationParams): string {
  if (!params) {
    return template
  }

  return template.replace(/\{([a-zA-Z0-9_.-]+)\}/g, (match, name: string) => {
    const value = params[name]
    return value === null || value === undefined ? match : String(value)
  })
}

export function formatStatus(locale: LocaleMode, status: string | null | undefined): string {
  if (!status) {
    return translate(locale, "status.unknown")
  }

  const normalized = status.toLowerCase().replace(/[\s-]+/g, "_")
  const key = `status.${normalized}` as TranslationKey
  const translated = translations[locale][key] ?? translations.en[key]
  return translated ?? humanizeStatus(status)
}

export function formatDataState(locale: LocaleMode, state: string | null | undefined): string {
  if (!state) {
    return translate(locale, "dataState.ready")
  }

  const normalized = state.toLowerCase().replace(/[\s-]+/g, "_")
  const key = `dataState.${normalized}` as TranslationKey
  const translated = translations[locale][key] ?? translations.en[key]
  return translated ?? formatStatus(locale, state)
}

export function formatDateTime(locale: LocaleMode, value: string | number | Date | null | undefined): string {
  if (!value) {
    return "--"
  }

  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) {
    return String(value)
  }

  return new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en-US", {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(date)
}

export function localizeValue(locale: LocaleMode, value: string, prefix: string): string {
  const key = `${prefix}.${value}` as TranslationKey
  const translated = translations[locale][key] ?? translations.en[key]
  return translated ?? value
}

function humanizeStatus(status: string): string {
  return status
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}
