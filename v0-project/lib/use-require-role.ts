"use client"

import * as React from "react"
import { useRouter } from "next/navigation"

import { useSession } from "@/lib/session"

function landingFor(role: string): string {
  switch (role) {
    case "health_worker":
      return "/dashboard/worker"
    case "doctor":
    case "ophthalmologist":
      return "/dashboard/doctor"
    case "admin":
      return "/admin"
    default:
      return "/dashboard/patient"
  }
}

/**
 * Client-side route guard. Redirects to /login when there is no session, or
 * to the caller's own landing page when the session role isn't allowed.
 *
 * `ready` is derived synchronously during render — no intermediate loading
 * state — because SessionProvider hydrates from localStorage before render.
 */
export function useRequireRole(allowed: string[]) {
  const { user } = useSession()
  const router = useRouter()

  const ready = Boolean(user && allowed.includes(user.role))

  React.useEffect(() => {
    if (!user) {
      router.replace("/login")
      return
    }
    if (!allowed.includes(user.role)) {
      router.replace(landingFor(user.role))
    }
  }, [user, allowed, router])

  return { user, ready }
}