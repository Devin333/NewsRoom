"use client"

import { MethodsPage } from "@/components/papers/methods/methods-page"
import { useUiStore } from "@/stores/ui-store"

export default function PapersMethodsPageRoute() {
  const locale = useUiStore((state) => state.locale)

  return <MethodsPage locale={locale} />
}
