"use client"

import { createContext, useContext, useReducer, useCallback, useEffect, useRef } from "react"

type ToastType = "success" | "error" | "info"
type Toast = { id: number; type: ToastType; message: string }
type Action =
  | { type: "ADD"; toast: Toast }
  | { type: "REMOVE"; id: number }

const ToastContext = createContext<{
  toast: (message: string, type?: ToastType) => void
} | null>(null)

function reducer(state: Toast[], action: Action): Toast[] {
  if (action.type === "ADD") return [...state, action.toast]
  return state.filter((t) => t.id !== action.id)
}

const icons: Record<ToastType, string> = {
  success: "✓",
  error: "✕",
  info: "i"
}

const styles: Record<ToastType, string> = {
  success: "border-good/20 bg-white text-good",
  error:   "border-bad/20 bg-white text-bad",
  info:    "border-line bg-white text-ink"
}

function ToastItem({ toast, onRemove }: { toast: Toast; onRemove: () => void }) {
  useEffect(() => {
    const t = setTimeout(onRemove, 4000)
    return () => clearTimeout(t)
  }, [onRemove])

  return (
    <div
      className={`flex items-start gap-2.5 rounded-lg border px-3.5 py-3 shadow-card text-sm animate-in slide-in-from-bottom-2 fade-in duration-200 ${styles[toast.type]}`}
    >
      <span className="mt-px text-xs font-bold">{icons[toast.type]}</span>
      <span className="flex-1 text-ink">{toast.message}</span>
      <button onClick={onRemove} className="ml-1 text-subtle hover:text-ink">✕</button>
    </div>
  )
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, dispatch] = useReducer(reducer, [])
  const counter = useRef(0)

  const toast = useCallback((message: string, type: ToastType = "info") => {
    const id = ++counter.current
    dispatch({ type: "ADD", toast: { id, type, message } })
  }, [])

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="fixed bottom-5 right-5 z-50 flex w-80 flex-col gap-2">
        {toasts.map((t) => (
          <ToastItem
            key={t.id}
            toast={t}
            onRemove={() => dispatch({ type: "REMOVE", id: t.id })}
          />
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error("useToast must be used within ToastProvider")
  return ctx.toast
}
