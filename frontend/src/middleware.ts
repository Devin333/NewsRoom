import { NextRequest, NextResponse } from "next/server"
import { NEWSROOM_SESSION_COOKIE } from "@/lib/auth/session"
import { getFrontendSurface, type FrontendSurface } from "@/lib/frontend-surface"

const PORTAL_PREFIXES = ["/news", "/topics", "/tech", "/reports", "/search", "/papers", "/community"]
const ADMIN_PREFIXES = ["/studio", "/admin"]

export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl
  const surface = getFrontendSurface()

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

function isPublicPath(pathname: string, surface: FrontendSurface) {
  return (
    (surface === "portal" && pathname === "/") ||
    (surface === "portal" && isResearchReadPath(pathname)) ||
    pathname.startsWith("/login") ||
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

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
}
