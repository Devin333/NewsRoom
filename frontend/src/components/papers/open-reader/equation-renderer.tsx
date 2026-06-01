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
        throwOnError: true,
        strict: "ignore",
        trust: false,
      })
    } catch {
      return null
    }
  }, [normalized])

  if (!rendered) {
    return <pre className={styles.equationPlain}>{readableMathFallback(normalized || value)}</pre>
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
        throwOnError: true,
        strict: "ignore",
        trust: false,
      })
    } catch {
      return null
    }
  }, [normalized])

  if (!rendered) {
    return <span className={styles.inlineMathPlain}>{fallback || readableMathFallback(normalized || value)}</span>
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

function readableMathFallback(value: string) {
  let text = stripEquationDelimiters(normalizeEquation(value))
  text = replaceSimpleFractions(text)
  text = stripMathWrappers(text)
  const replacements: Record<string, string> = {
    "\\alpha": "alpha",
    "\\beta": "beta",
    "\\gamma": "gamma",
    "\\delta": "delta",
    "\\epsilon": "epsilon",
    "\\varepsilon": "epsilon",
    "\\lambda": "lambda",
    "\\mu": "mu",
    "\\sigma": "sigma",
    "\\tau": "tau",
    "\\theta": "theta",
    "\\phi": "phi",
    "\\psi": "psi",
    "\\omega": "omega",
    "\\Delta": "Delta",
    "\\Sigma": "Sigma",
    "\\circ": "deg",
    "\\times": "x",
    "\\cdot": "*",
    "\\pm": "+/-",
    "\\in": "in",
    "\\sim": "~",
    "\\leq": "<=",
    "\\le": "<=",
    "\\geq": ">=",
    "\\ge": ">=",
    "\\neq": "!=",
    "\\to": "->",
    "\\rightarrow": "->",
    "\\leftarrow": "<-",
    "\\ldots": "...",
    "\\cdots": "...",
    "\\dots": "...",
    "\\sum": "sum",
  }
  for (const [source, target] of Object.entries(replacements).sort((left, right) => right[0].length - left[0].length)) {
    text = text.split(source).join(target)
  }
  return text
    .replace(/\\[,;:!]/g, " ")
    .replace(/\\\|/g, "|")
    .replace(/\\\{/g, "(")
    .replace(/\\\}/g, ")")
    .replace(/\\([_%&])/g, "$1")
    .replace(/\\[A-Za-z]+\*?\s*\{\s*([^{}]*?)\s*\}/g, "$1")
    .replace(/\\([A-Za-z]+)\*?/g, "$1")
    .replace(/\^\s*\{\s*([^{}]+?)\s*\}/g, "^$1")
    .replace(/_\s*\{\s*([^{}]+?)\s*\}/g, "_$1")
    .replace(/[{}]/g, "")
    .replace(/\s+/g, " ")
    .trim()
}

function replaceSimpleFractions(value: string) {
  let text = value
  let previous = ""
  const fractionPattern = /\\(?:dfrac|tfrac|frac)\s*\{([^{}]*)\}\s*\{([^{}]*)\}/g
  while (previous !== text) {
    previous = text
    text = text.replace(fractionPattern, (_match, numerator: string, denominator: string) => {
      return `${readableMathFallback(numerator)}/${readableMathFallback(denominator)}`
    })
  }
  return text
}

function stripMathWrappers(value: string) {
  let text = value
  let previous = ""
  const wrapperPattern = /\\(?:mathbf|mathrm|mathcal|mathbb|mathsf|mathtt|textrm|text|operatorname|hat|bar|tilde|vec|boldsymbol|bm)\*?\s*\{([^{}]*)\}/g
  while (previous !== text) {
    previous = text
    text = text.replace(/\\sqrt\s*\{([^{}]*)\}/g, (_match, body: string) => `sqrt(${readableMathFallback(body)})`)
    text = text.replace(wrapperPattern, "$1")
  }
  return text.replace(/\\(?:left|right)/g, "")
}
