"use client"

import * as React from "react"

import type { TokenResponse, UserOut } from "@/lib/api"

const SESSION_KEY = "netrascan.session.v1"

interface SessionState {
  token: string
  user: UserOut
}

interface SessionContextValue {
  user: UserOut | null
  token: string | null
  signIn: (payload: TokenResponse) => void
  signOut: () => void
}

const SessionContext = React.createContext<SessionContextValue | null>(null)

function loadSession(): SessionState | null {
  if (typeof window === "undefined") return null
  try {
    const raw = window.localStorage.getItem(SESSION_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as SessionState
    if (!parsed.token || !parsed.user) return null
    return parsed
  } catch {
    return null
  }
}

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = React.useState<SessionState | null>(() =>
    loadSession(),
  )

  const signIn = React.useCallback((payload: TokenResponse) => {
    const next: SessionState = { token: payload.access_token, user: payload.user }
    window.localStorage.setItem(SESSION_KEY, JSON.stringify(next))
    setSession(next)
  }, [])

  const signOut = React.useCallback(() => {
    window.localStorage.removeItem(SESSION_KEY)
    setSession(null)
  }, [])

  const value = React.useMemo(
    () => ({
      user: session?.user ?? null,
      token: session?.token ?? null,
      signIn,
      signOut,
    }),
    [session, signIn, signOut],
  )

  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  )
}

export function useSession(): SessionContextValue {
  const ctx = React.useContext(SessionContext)
  if (!ctx) {
    throw new Error("useSession must be used within a SessionProvider")
  }
  return ctx
}

export const rolePath: Record<string, string> = {
  patient: "/dashboard/patient",
  health_worker: "/dashboard/worker",
  doctor: "/doctor",
  ophthalmologist: "/doctor",
  admin: "/admin",
}

export function defaultRoleLanding(role: string): string {
  return rolePath[role] ?? "/login"
}