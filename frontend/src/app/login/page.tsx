import { Suspense } from "react"
import { LoginForm } from "@/app/login/login-form"
import { defaultPostLoginPath } from "@/lib/frontend-surface"

export const dynamic = "force-dynamic"

export default function LoginPage() {
  const defaultNextPath = defaultPostLoginPath()

  return (
    <Suspense fallback={<LoginShell />}>
      <LoginForm defaultNextPath={defaultNextPath} />
    </Suspense>
  )
}

function LoginShell() {
  return (
    <main className="flex min-h-[calc(100vh-8rem)] items-center justify-center px-4 py-12">
      <section className="w-full max-w-md rounded-md border border-border bg-card p-6 shadow-sm">
        <div className="h-6 w-40 rounded-sm bg-secondary" />
        <div className="mt-6 h-10 rounded-md bg-secondary" />
        <div className="mt-4 h-10 rounded-md bg-secondary" />
      </section>
    </main>
  )
}
