import { apiGet, apiPost } from "@/lib/api/client"
import type { AuthSession } from "@/lib/papers/types"

type ApiEnvelope<T> = {
  success: boolean
  data?: T | null
  error?: {
    code: string
    message: string
    requestId?: string
    request_id?: string | null
  } | null
}

export type AuthSessionStatus = {
  initialized: boolean
  session: AuthSession | null
}

export async function fetchAuthSession(init?: RequestInit): Promise<AuthSessionStatus> {
  const envelope = await apiGet<ApiEnvelope<AuthSessionStatus>>("/api/auth/session", init)
  return unwrapEnvelope(envelope)
}

export async function bootstrapAccount(username: string, password: string, init?: RequestInit): Promise<AuthSession> {
  const envelope = await apiPost<ApiEnvelope<{ session: AuthSession }>>(
    "/api/auth/bootstrap",
    { username, password },
    init
  )
  return unwrapEnvelope(envelope).session
}

export async function login(username: string, password: string, init?: RequestInit): Promise<AuthSession> {
  const envelope = await apiPost<ApiEnvelope<{ session: AuthSession }>>(
    "/api/auth/login",
    { username, password },
    init
  )
  return unwrapEnvelope(envelope).session
}

export async function logout(init?: RequestInit): Promise<void> {
  await apiPost<ApiEnvelope<{ revoked: boolean }>>("/api/auth/logout", undefined, init)
}

function unwrapEnvelope<T>(envelope: ApiEnvelope<T>): T {
  if (envelope.success && envelope.data) {
    return envelope.data
  }
  throw new Error(envelope.error?.message ?? "Auth request failed")
}
