"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { Eye, EyeOff, HelpCircle, Info } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Field,
  FieldContent,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import { InputGroup } from "@/components/ui/input-group"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Spinner } from "@/components/ui/spinner"
import { authApi, ApiError } from "@/lib/api"
import { defaultRoleLanding, useSession } from "@/lib/session"

export type LoginFormMode = "user" | "doctor" | "admin"
export type UserRole = "patient" | "worker" | "doctor" | "ophthalmologist"

export interface LoginFormProps {
  mode: LoginFormMode
}

const roleConfig: Record<
  UserRole,
  { label: string; buttonLabel: string; context: string; apiRole: string }
> = {
  patient: {
    label: "Patient",
    buttonLabel: "Continue as Patient",
    apiRole: "patient",
    context:
      "You'll access your own eye-care records, screening history, and referrals.",
  },
  worker: {
    label: "Health Worker",
    buttonLabel: "Continue as Health Worker",
    apiRole: "health_worker",
    context:
      "You'll run village screenings, add patient records, and send referrals for specialist review.",
  },
  doctor: {
    label: "Doctor",
    buttonLabel: "Continue as Doctor",
    apiRole: "doctor",
    context:
      "You'll review incoming screenings and support health workers with ophthalmologist guidance.",
  },
  ophthalmologist: {
    label: "Ophthalmologist",
    buttonLabel: "Continue as Ophthalmologist",
    apiRole: "ophthalmologist",
    context:
      "You'll review AI-screened cases, sign off reports, and generate patient summaries.",
  },
}

const roleOrder: UserRole[] = ["patient", "worker", "doctor", "ophthalmologist"]
const roleLabel: Record<UserRole, string> = {
  patient: "Patient",
  worker: "Health Worker",
  doctor: "Doctor",
  ophthalmologist: "Ophthalmologist",
}

function validateEmail(email: string): string | null {
  if (!email.trim()) return "Email is required."
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim()))
    return "Enter a valid email address."
  return null
}

function validatePassword(password: string): string | null {
  if (!password) return "Password is required."
  return null
}

export function LoginForm({ mode }: LoginFormProps) {
  const isAdmin = mode === "admin"
  const isDoctor = mode === "doctor"
  const router = useRouter()
  const { signIn } = useSession()

  const [role, setRole] = React.useState<UserRole>(
    isDoctor ? "ophthalmologist" : "patient",
  )
  const [email, setEmail] = React.useState("")
  const [password, setPassword] = React.useState("")
  const [showPassword, setShowPassword] = React.useState(false)
  const [errors, setErrors] = React.useState<{
    email?: string | null
    password?: string | null
  }>({})
  const [serverError, setServerError] = React.useState<string | null>(null)

  const [status, setStatus] = React.useState<
    "idle" | "submitting" | "submitted"
  >("idle")
  const [submitOpen, setSubmitOpen] = React.useState(false)
  const [forgotOpen, setForgotOpen] = React.useState(false)
  const [helpOpen, setHelpOpen] = React.useState(false)

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()

    const emailError = validateEmail(email)
    const passwordError = validatePassword(password)
    const nextErrors = { email: emailError, password: passwordError }

    setErrors(nextErrors)
    setServerError(null)

    if (emailError || passwordError) {
      return
    }

    setStatus("submitting")
    try {
      const payload = await authApi.login(email, password)

      if (isDoctor) {
        if (payload.user.role !== "ophthalmologist" && payload.user.role !== "doctor") {
          setServerError(
            "That account is not a reviewing clinician. Ophthalmologists sign in here; patients and health workers use the user login.",
          )
          return
        }
      } else if (isAdmin) {
        if (payload.user.role !== "admin") {
          setServerError(
            "That account is not an administrator. Use the user login for the dashboard you need.",
          )
          return
        }
      } else if (payload.user.role !== roleConfig[role].apiRole) {
        const expected = roleConfig[role].label
        setServerError(
          `That account is registered as a ${
            payload.user.role === "health_worker"
              ? "Health Worker"
              : payload.user.role === "doctor"
                ? "Doctor"
                : payload.user.role === "ophthalmologist"
                  ? "Ophthalmologist"
                  : "Patient"
          }. Switch the role toggle to ${expected} and try again.`,
        )
        return
      }

      signIn(payload)
      setStatus("submitted")
      router.push(defaultRoleLanding(payload.user.role))
    } catch (error) {
      const message =
        error instanceof ApiError
          ? error.detail ?? error.message
          : "Unable to reach the NetraScan backend. Is the API server running?"
      setServerError(message)
      setStatus("idle")
    }
  }

  const buttonLabel = isAdmin
    ? "Sign in to Administration"
    : isDoctor
      ? "Sign in to Review Portal"
      : roleConfig[role].buttonLabel

  return (
    <div className="flex w-full flex-col gap-5">
      {/* Demo backend notice */}
      <Alert variant="default" className="bg-secondary/40">
        <Info className="text-primary" />
        <AlertTitle>Live demo backend</AlertTitle>
        <AlertDescription>
          Credentials are checked against the NetraScan API. Demo accounts:
          <br />
          Patients: patient@example.org (Anita) · mo.faizal@example.org ·
          lakshmi@example.org · aapti@example.org
          <br />
          worker@example.org · doctor@example.org ·
          ophthalmologist@netrascan.in · admin@netrascan.in
          <br />
          (passwords end in &ldquo;123!&rdquo;).
        </AlertDescription>
      </Alert>

      {/* Server error */}
      {serverError && (
        <Alert variant="destructive">
          <HelpCircle />
          <AlertTitle>Sign-in failed</AlertTitle>
          <AlertDescription>{serverError}</AlertDescription>
        </Alert>
      )}

      <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-5">
        {/* Role selection — user login only */}
        {!isAdmin && (
          <FieldGroup>
            <div className="flex flex-col gap-2">
              <span
                id="role-label"
                className="text-sm font-medium text-foreground"
              >
                I&apos;m signing in as
              </span>
              <ToggleGroup
                aria-labelledby="role-label"
                value={[role]}
                multiple={false}
                onValueChange={(value) => {
                  if (value.length > 0) {
                    setRole(value[0] as UserRole)
                  }
                }}
              >
                {roleOrder.map((r) => (
                  <ToggleGroupItem key={r} value={r}>
                    {roleLabel[r]}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            </div>
            <p
              aria-live="polite"
              className="text-sm leading-relaxed text-muted-foreground"
            >
              {roleConfig[role].context}
            </p>
          </FieldGroup>
        )}

        {/* Email */}
        <Field>
          <FieldLabel htmlFor={isAdmin ? "admin-email" : "email"}>
            Email address
          </FieldLabel>
          <FieldContent>
            <InputGroup>
              <Input
                id={isAdmin ? "admin-email" : "email"}
                type="email"
                name="email"
                autoComplete="email"
                inputMode="email"
                placeholder="you@example.org"
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value)
                  if (errors.email) {
                    setErrors((prev) => ({ ...prev, email: null }))
                  }
                }}
                aria-invalid={errors.email ? true : undefined}
                aria-describedby={
                  errors.email
                    ? isAdmin
                      ? "admin-email-error"
                      : "email-error"
                    : undefined
                }
              />
            </InputGroup>
            <FieldError id={isAdmin ? "admin-email-error" : "email-error"}>
              {errors.email}
            </FieldError>
          </FieldContent>
        </Field>

        {/* Password */}
        <Field>
          <div className="flex w-full items-center justify-between">
            <FieldLabel htmlFor={isAdmin ? "admin-password" : "password"}>
              Password
            </FieldLabel>
            <button
              type="button"
              onClick={() => setForgotOpen(true)}
              className="text-sm font-medium text-primary underline-offset-4 outline-none hover:underline focus-visible:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            >
              Forgot password?
            </button>
          </div>
          <FieldContent>
            <InputGroup>
              <Input
                id={isAdmin ? "admin-password" : "password"}
                type={showPassword ? "text" : "password"}
                name="password"
                autoComplete="current-password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value)
                  if (errors.password) {
                    setErrors((prev) => ({ ...prev, password: null }))
                  }
                }}
                aria-invalid={errors.password ? true : undefined}
                aria-describedby={
                  errors.password
                    ? isAdmin
                      ? "admin-password-error"
                      : "password-error"
                    : undefined
                }
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="mr-1.5 shrink-0 text-muted-foreground hover:text-foreground"
                aria-label={
                  showPassword ? "Hide password" : "Show password"
                }
                aria-pressed={showPassword}
                onClick={() => setShowPassword((v) => !v)}
              >
                {showPassword ? (
                  <EyeOff className="size-4" />
                ) : (
                  <Eye className="size-4" />
                )}
              </Button>
            </InputGroup>
            <FieldError id={isAdmin ? "admin-password-error" : "password-error"}>
              {errors.password}
            </FieldError>
          </FieldContent>
        </Field>

        {/* Submit */}
        <Button
          type="submit"
          size="lg"
          disabled={status === "submitting"}
          className="mt-1 w-full"
        >
          {status === "submitting" ? (
            <>
              <Spinner size="sm" />
              Signing in&hellip;
            </>
          ) : (
            buttonLabel
          )}
        </Button>

        {/* Live region for assistive technology */}
        <span id="login-status" className="sr-only" aria-live="polite">
          {status === "submitting"
            ? "Signing in…"
            : status === "submitted"
              ? "Signed in. Redirecting to your dashboard."
              : serverError
                ? "Sign-in failed. Check the error message above."
                : errors.email || errors.password
                  ? "Please fix the highlighted fields."
                  : ""}
        </span>

        {/* Cross-navigation */}
        <div className="flex flex-col items-center gap-1 text-sm text-muted-foreground">
          {isAdmin ? (
            <p>
              No public administrator sign-up exists. Prefer the{" "}
              <Link
                href="/login"
                className="font-medium text-primary underline-offset-4 outline-none hover:underline focus-visible:underline focus-visible:ring-2 focus-visible:ring-ring"
              >
                user login
              </Link>
              {"."}
            </p>
          ) : (
            <p>
              Are you an administrator?{" "}
              <Link
                href="/admin/login"
                className="font-medium text-primary underline-offset-4 outline-none hover:underline focus-visible:underline focus-visible:ring-2 focus-visible:ring-ring"
              >
                Go to admin login
              </Link>
              {"."}
            </p>
          )}
        </div>
      </form>

      {/* Prototype help */}
      <div>
        <button
          type="button"
          onClick={() => setHelpOpen(true)}
          className="text-sm text-muted-foreground underline-offset-4 outline-none hover:text-foreground hover:underline focus-visible:underline focus-visible:ring-2 focus-visible:ring-ring"
        >
          What happens to my credentials?
        </button>
      </div>

      {/* Submission feedback dialog — only reached on unexpected navigation */}
      <Dialog open={submitOpen} onOpenChange={setSubmitOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Signed in</DialogTitle>
            <DialogDescription>
              {isAdmin ? (
                <>
                  You signed in to the <strong>Administrator</strong> portal.
                </>
              ) : (
                <>
                  You signed in to the <strong>{roleConfig[role].label}</strong>{" "}
                  portal.
                </>
              )}{" "}
              Redirecting to your dashboard.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter showCloseButton />
        </DialogContent>
      </Dialog>

      {/* Forgot password dialog */}
      <Dialog open={forgotOpen} onOpenChange={setForgotOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Password recovery isn&apos;t connected</DialogTitle>
            <DialogDescription>
              Self-service password reset is not enabled yet, so no email was
              dispatched. Contact your NetraScan administrator to reset your
              password.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter showCloseButton />
        </DialogContent>
      </Dialog>

      {/* Credentials dialog */}
      <Dialog open={helpOpen} onOpenChange={setHelpOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>What happens to my credentials?</DialogTitle>
            <DialogDescription>
              Your password is sent over HTTPS to the NetraScan API, hashed
              there with bcrypt, and verified against the demo database. The
              returned bearer token is stored in this browser only for the
              current session. No medical assessment is performed from the
              login screen.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter showCloseButton />
        </DialogContent>
      </Dialog>
    </div>
  )
}