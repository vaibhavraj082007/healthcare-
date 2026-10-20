import type { Metadata } from "next"

import { LoginShell } from "@/components/auth/login-shell"
import { LoginForm } from "@/components/auth/login-form"

export const metadata: Metadata = {
  title: "Ophthalmologist login",
  description:
    "NetraScan telemedicine review portal for ophthalmologists and doctors. Sign in to review AI-screened cases and sign off reports.",
}

export default function DoctorLoginPage() {
  return (
    <LoginShell mode="doctor">
      <LoginForm mode="doctor" />
    </LoginShell>
  )
}