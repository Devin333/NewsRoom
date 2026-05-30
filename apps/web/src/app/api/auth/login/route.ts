import { NextResponse } from "next/server"
import { cookies } from "next/headers"

export async function POST(request: Request) {
  const { token } = await request.json()
  const expected = process.env.NEWSROOM_CONSOLE_TOKEN

  if (!expected) {
    return NextResponse.json({ error: "Server not configured" }, { status: 500 })
  }
  if (token !== expected) {
    return NextResponse.json({ error: "Invalid token" }, { status: 401 })
  }

  const cookieStore = await cookies()
  cookieStore.set("newsroom_session", token, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 30
  })

  return NextResponse.json({ ok: true })
}
