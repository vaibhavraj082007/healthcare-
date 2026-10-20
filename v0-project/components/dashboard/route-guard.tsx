"use client"

import * as React from "react"

import { Spinner } from "@/components/ui/spinner"
import { useRequireRole } from "@/lib/use-require-role"

function LoadingGate() {
  return (
    <div className="flex min-h-dvh items-center justify-center">
      <Spinner size="lg" />
      <span className="sr-only" aria-live="polite">
        Checking your session
      </span>
    </div>
  )
}

/**
 * Renders children only after the (client-side) session is verified against
 * the allowed roles. While checking, or when redirected, shows a loader.
 */
export function RequireRole({
  roles,
  children,
}: {
  roles: string[]
  children: React.ReactNode
}) {
  const { ready } = useRequireRole(roles)
  if (!ready) return <LoadingGate />
  return children
}