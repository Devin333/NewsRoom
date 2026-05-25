import { NextRequest, NextResponse } from "next/server"
import { NEWSROOM_SESSION_COOKIE } from "@/lib/auth/session"

const PROTECTED_PREFIXES = ["/news", "/topics", "/tech", "/reports", "/search", "/papers"]

export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl
  if (!isProtectedPath(pathname)) {
    return NextResponse.next()
  }

  const sessionCookie = request.cookies.get(NEWSROOM_SESSION_COOKIE)?.value
  if (sessionCookie) {
    return NextResponse.next()
  }

  const loginUrl = request.nextUrl.clone()
  loginUrl.pathname = "/login"
  loginUrl.search = ""
  loginUrl.searchParams.set("next", `${pathname}${search}`)
  return NextResponse.redirect(loginUrl)
}

function isProtectedPath(pathname: string) {
  if (pathname === "/") {
    return true
  }
  if (
    pathname.startsWith("/login") ||
    pathname.startsWith("/api/") ||
    pathname.startsWith("/studio") ||
    pathname.startsWith("/_next/") ||
    pathname === "/favicon.ico"
  ) {
    return false
  }
  return PROTECTED_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`))
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
}
