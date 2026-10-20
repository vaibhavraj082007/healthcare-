"use client"

import * as React from "react"
import { useRouter } from "next/navigation"

import { Spinner } from "@/components/ui/spinner"
import { useSession } from "@/lib/session"

export default function DashboardIndexPage() {
  const { user } = useSession()
  const router = useRouter()

  React.useEffect(() => {
    if (!user) {
      router.replace("/login")
      return
    }
    const path =
      user.role === "admin"
        ? "/admin"
        : user.role === "health_worker"
          ? "/dashboard/worker"
          : user.role === "doctor"
            ? "/dashboard/doctor"
            : "/dashboard/patient"
    router.replace(path)
  }, [user, router])

  return (
    <div className="flex min-h-dvh items-center justify-center">
      <Spinner size="lg" />
      <span className="sr-only" aria-live="polite">
        Taking you to your dashboard
      </span>
    </div>
  )
}