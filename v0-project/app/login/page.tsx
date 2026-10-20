import type { Metadata } from "next"

import { LoginShell } from "@/components/auth/login-shell"
import { LoginForm } from "@/components/auth/login-form"

export const metadata: Metadata = {
  title: "Sign in",
  description:
    "Sign in to NetraScan as a patient, health worker, or doctor. Interactive frontend preview only.",
}

export default function LoginPage() {
  return (
    <LoginShell mode="user">
      <LoginForm mode="user" />
    </LoginShell>
  )
}