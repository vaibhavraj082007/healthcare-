import type { Metadata } from "next"
import { Suspense } from "react"

import { Spinner } from "@/components/ui/spinner"
import { CaseDetailClient } from "./case-detail-client"

export function generateStaticParams() {
  // Case ids are created at runtime (one per screening report); never
  // bake them into the build — render on every request.
  return []
}

export const metadata: Metadata = {
  title: "Case — NetraScan",
  description: "Case detail for the NetraScan doctor portal.",
}

function CaseLoading() {
  return (
    <div className="flex min-h-dvh items-center justify-center">
      <Spinner size="lg" />
      <span className="sr-only" aria-live="polite">
        Loading the case…
      </span>
    </div>
  )
}

export default function CasePage() {
  return (
    <Suspense fallback={<CaseLoading />}>
      <CaseDetailClient />
    </Suspense>
  )
}