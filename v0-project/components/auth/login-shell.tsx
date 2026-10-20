"use client"

import * as React from "react"
import { Eye } from "lucide-react"

type LoginShellMode = "user" | "doctor" | "admin"

interface LoginShellProps {
  children: React.ReactNode
  mode: LoginShellMode
}

const modeConfig = {
  user: {
    title: "Sign in to NetraScan",
    subtitle: "Access your screening portal",
  },
  doctor: {
    title: "Ophthalmologist Review Portal",
    subtitle: "Review AI-screened cases and sign off reports",
  },
  admin: {
    title: "NetraScan Administration",
    subtitle: "Authorized administrator access only",
  },
}

export function LoginShell({ children, mode }: LoginShellProps) {
  const config = modeConfig[mode]

  return (
    <div className="flex min-h-dvh flex-col lg:h-dvh lg:flex-row lg:overflow-hidden">
      {/* Visual / branding panel */}
      <div className="relative flex flex-col bg-primary lg:w-[45%] lg:h-full">
        {/* Mobile: condensed brand header */}
        <div className="flex items-center gap-3 px-5 py-4 lg:hidden">
          <div className="flex size-9 items-center justify-center rounded-full bg-white/15">
            <Eye className="size-5 text-white" />
          </div>
          <span className="font-heading text-lg font-semibold tracking-tight text-white">
            NetraScan
          </span>
        </div>

        {/* Desktop: full storytelling panel */}
        <div className="hidden flex-1 flex-col px-10 py-8 lg:flex">
          <div>
            <div className="mb-8 flex items-center gap-3">
              <div className="flex size-10 items-center justify-center rounded-full bg-white/15">
                <Eye className="size-6 text-white" />
              </div>
              <span className="font-heading text-xl font-semibold tracking-tight text-white">
                NetraScan
              </span>
            </div>

            <h1 className="font-heading text-3xl font-semibold leading-snug tracking-tight text-white xl:text-4xl">
              A clearer future
              <br />
              for every eye.
            </h1>

            <p className="mt-3 max-w-md text-[0.95rem] leading-relaxed text-white/80">
              Connecting rural communities with expert ophthalmologists through
              accessible screening and specialist review &mdash; designed for the
              villages that need it most.
            </p>
          </div>

          {/* Illustration — flexes to fill remaining space */}
          <div className="mt-5 min-h-0 flex-1 overflow-hidden rounded-xl bg-white/10">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src="/images/netrascan-consultation.svg"
              alt="An eye-care professional conducting a vision screening in a rural Indian setting"
              className="h-full w-full object-cover object-top"
              loading="eager"
            />
          </div>

          <p className="mt-3 text-xs leading-relaxed text-white/50">
            NetraScan &mdash; a concept by Binary Bandits, Smart India Hackathon 2026
          </p>
        </div>
      </div>

      {/* Form panel */}
      <div className="flex flex-1 flex-col bg-background px-5 py-5 sm:px-8 lg:px-14 lg:py-8 lg:h-full lg:overflow-y-auto">
        <div className="mx-auto flex w-full max-w-md flex-1 flex-col">
          {/* Mobile brand (shown when visual panel is collapsed) */}
          <div className="mb-8 flex items-center gap-2.5 lg:hidden">
            <div className="flex size-8 items-center justify-center rounded-full bg-primary">
              <Eye className="size-4.5 text-primary-foreground" />
            </div>
            <span className="font-heading text-base font-semibold tracking-tight text-foreground">
              NetraScan
            </span>
          </div>

          <div className="mb-6">
            <h2 className="font-heading text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
              {config.title}
            </h2>
            <p className="mt-1.5 text-sm text-muted-foreground">
              {config.subtitle}
            </p>
          </div>

          <div className="flex-1">{children}</div>

          {/* Footer credit */}
          <div className="mt-8 border-t border-border pt-5 text-xs text-muted-foreground lg:hidden">
            <p>
              NetraScan &mdash; Binary Bandits / Smart India Hackathon 2026
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
