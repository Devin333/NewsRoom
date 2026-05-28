"use client"

import katex from "katex"
import { useMemo } from "react"

import styles from "./open-reader.module.css"

export function EquationRenderer({ value }: { value: string }) {
  const normalized = normalizeEquation(value)
  const rendered = useMemo(() => {
    if (!normalized) return null
    try {
      return katex.renderToString(stripEquationDelimiters(normalized), {
        displayMode: true,
        throwOnError: false,
        strict: "ignore",
        trust: false,
      })
    } catch {
      return null
    }
  }, [normalized])

  if (!rendered) {
    return <pre className={styles.equationPlain}>{normalized || value}</pre>
  }

  return (
    <div
      className={styles.equationMath}
      aria-label={normalized}
      dangerouslySetInnerHTML={{ __html: rendered }}
    />
  )
}

export function InlineMathRenderer({ value, fallback }: { value: string; fallback?: string }) {
  const normalized = normalizeEquation(value)
  const rendered = useMemo(() => {
    if (!normalized) return null
    try {
      return katex.renderToString(stripEquationDelimiters(normalized), {
        displayMode: false,
        throwOnError: false,
        strict: "ignore",
        trust: false,
      })
    } catch {
      return null
    }
  }, [normalized])

  if (!rendered) {
    return <span className={styles.inlineMathPlain}>{fallback || normalized || value}</span>
  }

  return (
    <span
      className={styles.inlineMath}
      aria-label={fallback || normalized}
      dangerouslySetInnerHTML={{ __html: rendered }}
    />
  )
}

function normalizeEquation(value: string) {
  return value.replace(/\s+/g, " ").trim()
}

function stripEquationDelimiters(value: string) {
  const trimmed = value.trim()
  const pairs: Array<[string, string]> = [
    ["$$", "$$"],
    ["\\[", "\\]"],
    ["\\(", "\\)"],
    ["$", "$"],
  ]
  for (const [start, end] of pairs) {
    if (trimmed.startsWith(start) && trimmed.endsWith(end) && trimmed.length > start.length + end.length) {
      return trimmed.slice(start.length, trimmed.length - end.length).trim()
    }
  }
  return trimmed
}
