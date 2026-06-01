import { NextRequest, NextResponse } from "next/server"
import { NEWSROOM_SESSION_COOKIE } from "@/lib/auth/session"
import { getFrontendSurface, type FrontendSurface } from "@/lib/frontend-surface"

const PORTAL_PREFIXES = ["/news", "/topics", "/tech", "/reports", "/search", "/papers", "/community"]
const ADMIN_PREFIXES = ["/studio", "/admin"]

export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl
  const surface = getFrontendSurface()

  if (isTemporaryFrontendAuthDisabled() && isLoginPath(pathname)) {
    return redirectToLoginBypassTarget(request, surface)
  }

  if (isPublicPath(pathname, surface)) {
    return NextResponse.next()
  }

  const surfaceRedirect = getCrossSurfaceRedirect(request, surface)
  if (surfaceRedirect) {
    return surfaceRedirect
  }

  if (!isProtectedPath(pathname)) {
    return NextResponse.next()
  }

  if (isTemporaryFrontendAuthDisabled()) {
    if (surface === "admin" && pathname === "/") {
      const studioUrl = request.nextUrl.clone()
      studioUrl.pathname = "/studio"
      studioUrl.search = ""
      return NextResponse.redirect(studioUrl)
    }
    return NextResponse.next()
  }

  const sessionCookie = request.cookies.get(NEWSROOM_SESSION_COOKIE)?.value
  if (sessionCookie) {
    if (surface === "admin" && pathname === "/") {
      const studioUrl = request.nextUrl.clone()
      studioUrl.pathname = "/studio"
      studioUrl.search = ""
      return NextResponse.redirect(studioUrl)
    }
    return NextResponse.next()
  }

  const loginUrl = request.nextUrl.clone()
  loginUrl.pathname = "/login"
  loginUrl.search = ""
  loginUrl.searchParams.set("next", `${pathname}${search}`)
  return NextResponse.redirect(loginUrl)
}

function isTemporaryFrontendAuthDisabled() {
  return process.env.NEWSROOM_ENABLE_FRONTEND_AUTH !== "true"
}

function isLoginPath(pathname: string) {
  return pathname === "/login" || pathname.startsWith("/login/") || pathname.startsWith("/login?")
}

function isPublicPath(pathname: string, surface: FrontendSurface) {
  return (
    (surface === "portal" && pathname === "/") ||
    (surface === "portal" && isResearchReadPath(pathname)) ||
    isLoginPath(pathname) ||
    pathname.startsWith("/api/") ||
    pathname.startsWith("/_next/") ||
    pathname === "/favicon.ico"
  )
}

function isResearchReadPath(pathname: string) {
  return pathname === "/papers" || pathname.startsWith("/papers/")
}

function isProtectedPath(pathname: string) {
  if (pathname === "/" || isAdminPath(pathname)) {
    return true
  }
  return isPortalPath(pathname)
}

function isPortalPath(pathname: string) {
  return PORTAL_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`))
}

function isAdminPath(pathname: string) {
  return ADMIN_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`))
}

function getCrossSurfaceRedirect(request: NextRequest, surface: FrontendSurface) {
  const { pathname, search } = request.nextUrl

  if (surface === "portal" && isAdminPath(pathname)) {
    return redirectToSurface(request, process.env.NEWSROOM_ADMIN_ORIGIN, `${pathname}${search}`, "/")
  }

  if (surface === "admin" && isPortalPath(pathname)) {
    return redirectToSurface(request, process.env.NEWSROOM_PORTAL_ORIGIN, `${pathname}${search}`, "/")
  }

  return null
}

function redirectToSurface(request: NextRequest, origin: string | undefined, targetPath: string, fallbackPath: string) {
  if (origin) {
    try {
      return NextResponse.redirect(new URL(targetPath, origin))
    } catch {
      // Fall back to the local surface home when the optional origin is malformed.
    }
  }

  const redirectUrl = request.nextUrl.clone()
  redirectUrl.pathname = fallbackPath
  redirectUrl.search = ""
  return NextResponse.redirect(redirectUrl)
}

function redirectToLoginBypassTarget(request: NextRequest, surface: FrontendSurface) {
  const targetPath = safeNextPath(
    request.nextUrl.searchParams.get("next"),
    surface === "admin" ? "/studio" : "/"
  )
  return NextResponse.redirect(new URL(targetPath, request.nextUrl.origin))
}

function safeNextPath(value: string | null, fallback: string) {
  if (!value || !value.startsWith("/") || value.startsWith("//") || isLoginPath(value)) {
    return fallback
  }
  return value
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
}
