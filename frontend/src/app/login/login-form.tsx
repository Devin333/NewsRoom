"use client"

import { FormEvent, useEffect, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { LockKeyhole } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { bootstrapAccount, fetchAuthSession, login } from "@/lib/auth/api"

export function LoginForm() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const nextPath = safeNextPath(searchParams.get("next"))
  const [initialized, setInitialized] = useState<boolean | null>(null)
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [status, setStatus] = useState<"idle" | "loading" | "success" | "error">("idle")
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchAuthSession()
      .then((result) => {
        if (cancelled) return
        setInitialized(result.initialized)
        if (result.session) {
          router.replace(nextPath)
        }
      })
      .catch((requestError) => {
        if (!cancelled) {
          setInitialized(true)
          setError(requestError instanceof Error ? requestError.message : "Session check failed")
        }
      })
    return () => {
      cancelled = true
    }
  }, [nextPath, router])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setStatus("loading")
    setError(null)
    try {
      if (initialized === false) {
        await bootstrapAccount(username, password)
      } else {
        await login(username, password)
      }
      setStatus("success")
      router.replace(nextPath)
      router.refresh()
    } catch (requestError) {
      setStatus("error")
      setError(requestError instanceof Error ? requestError.message : "Login failed")
    }
  }

  const isBootstrap = initialized === false
  const title = isBootstrap ? "Create the first NewsRoom account" : "Sign in to NewsRoom"

  return (
    <main className="flex min-h-[calc(100vh-8rem)] items-center justify-center px-4 py-12">
      <section className="w-full max-w-md rounded-md border border-border bg-card p-6 shadow-sm">
        <div className="mb-6 flex items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-md bg-secondary">
            <LockKeyhole className="size-5" />
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-normal">{title}</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {isBootstrap ? "Bootstrap is available because no account exists yet." : "Use your local account to continue."}
            </p>
          </div>
        </div>

        <form className="space-y-4" onSubmit={submit}>
          <label className="block text-sm font-medium">
            Username
            <Input
              className="mt-2"
              autoComplete="username"
              minLength={3}
              maxLength={64}
              required
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
          </label>
          <label className="block text-sm font-medium">
            Password
            <Input
              className="mt-2"
              autoComplete={isBootstrap ? "new-password" : "current-password"}
              minLength={8}
              maxLength={256}
              required
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          {error ? (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">
              {error}
            </div>
          ) : null}
          <Button type="submit" className="w-full" disabled={status === "loading" || initialized === null}>
            {status === "loading" ? "Working..." : isBootstrap ? "Create account" : "Sign in"}
          </Button>
        </form>
      </section>
    </main>
  )
}

function safeNextPath(value: string | null) {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.startsWith("/login")) {
    return "/papers"
  }
  return value
}
