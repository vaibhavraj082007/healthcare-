"use client"

import * as React from "react"
import { useRouter } from "next/navigation"

import { Spinner } from "@/components/ui/spinner"
import { useSession } from "@/lib/session"

const REVIEW_ROLES = ["doctor", "ophthalmologist"]

export default function DoctorIndexPage() {
  const { user } = useSession()
  const router = useRouter()

  React.useEffect(() => {
    if (!user) {
      router.replace("/doctor/login")
      return
    }
    if (!REVIEW_ROLES.includes(user.role)) {
      router.replace("/dashboard")
      return
    }
    router.replace("/doctor/dashboard")
  }, [user, router])

  return (
    <div className="flex min-h-dvh items-center justify-center">
      <Spinner size="lg" />
      <span className="sr-only" aria-live="polite">
        Loading the doctor portal…
      </span>
    </div>
  )
}