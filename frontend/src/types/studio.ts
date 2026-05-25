import type { ComponentType, ReactNode } from "react"

export type StudioApiError = {
  code: string
  message: string
  details?: unknown
  retryable?: boolean
  userActionRequired?: boolean
  requestId?: string
  status?: number
}

export type StudioModuleStatus = "ready" | "partial" | "fallback"

export type StudioNavigationItem = {
  label: string
  href: string
  description?: string
  icon?: ComponentType<{ className?: string }>
  status?: StudioModuleStatus
}

export type StudioNavigationGroup = {
  label: string
  items: StudioNavigationItem[]
}

export type StudioModuleEntry = {
  title: string
  description: string
  href: string
  coreObject: string
  targetApi: string
  status: StudioModuleStatus
  icon?: ComponentType<{ className?: string }>
  actionLabel?: string
}

export type StudioPageStateKind = "loading" | "empty" | "error"

export type StudioPageStateAction = {
  label: string
  onClick?: () => void
  href?: string
}

export type StudioPageState = {
  kind: StudioPageStateKind
  title: string
  description?: string
  action?: StudioPageStateAction
}

export type StudioFallbackNotice = {
  title?: string
  message: string
  requestId?: string
  error?: StudioApiError
  action?: ReactNode
}
