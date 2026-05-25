"use client"

import { useEffect, useState } from "react"
import { LogOut, UserCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { fetchAuthSession, logout } from "@/lib/auth/api"
import type { CurrentUser } from "@/lib/papers/types"

export function AccountMenu() {
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    fetchAuthSession()
      .then((result) => {
        if (!cancelled) {
          setUser(result.session?.user ?? null)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setUser(null)
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function signOut() {
    setLoading(true)
    try {
      await logout()
    } finally {
      window.location.href = "/login"
    }
  }

  if (!user) {
    return null
  }

  return (
    <div className="flex items-center gap-2">
      <span className="hidden max-w-32 truncate text-xs font-medium text-muted-foreground sm:inline-flex">
        <UserCircle className="mr-1 size-4" />
        {user.username}
      </span>
      <Button type="button" variant="ghost" size="icon" aria-label="Sign out" disabled={loading} onClick={signOut}>
        <LogOut className="size-4" />
      </Button>
    </div>
  )
}
