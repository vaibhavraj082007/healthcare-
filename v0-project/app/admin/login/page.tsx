import type { Metadata } from "next"

import { LoginShell } from "@/components/auth/login-shell"
import { LoginForm } from "@/components/auth/login-form"

export const metadata: Metadata = {
  title: "Admin login",
  description:
    "NetraScan administration login. Interactive frontend preview only — no access control is implemented.",
}

export default function AdminLoginPage() {
  return (
    <LoginShell mode="admin">
      <LoginForm mode="admin" />
    </LoginShell>
  )
}