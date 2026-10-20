"use client"

import * as React from "react"

import { DashboardShell } from "@/components/dashboard/dashboard-shell"
import { RequireRole } from "@/components/dashboard/route-guard"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import type { ModelInfo } from "@/lib/api"
import { dashboardApi } from "@/lib/api"
import { useSession } from "@/lib/session"
import { Info } from "lucide-react"

function ModelPanel({ model }: { model: ModelInfo }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="flex flex-col gap-1">
            <CardTitle className="text-base">{model.name}</CardTitle>
            <CardDescription>
              {model.family} · {model.task}
            </CardDescription>
          </div>
          <Badge tone={model.weights ? "success" : "warning"}>
            {model.weights ? "Weights loaded" : "Not loaded"}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="gap-1.5">
        <dl className="flex flex-col gap-1.5 text-sm">
          <div className="grid grid-cols-[140px_1fr] gap-2">
            <dt className="text-muted-foreground">Trained on</dt>
            <dd>{model.trained_on}</dd>
          </div>
          <div className="grid grid-cols-[140px_1fr] gap-2">
            <dt className="text-muted-foreground">Fine-tuned</dt>
            <dd>{model.fine_tuned ? "Yes" : "No — public pretrained checkpoint"}</dd>
          </div>
          <div className="grid grid-cols-[140px_1fr] gap-2">
            <dt className="text-muted-foreground">Weights path</dt>
            <dd className="break-all font-mono text-xs">{model.weights_path}</dd>
          </div>
          {Object.keys(model.validation).length > 0 && (
            <div className="grid grid-cols-[140px_1fr] gap-2">
              <dt className="text-muted-foreground">Validation</dt>
              <dd>
                {Object.entries(model.validation)
                  .map(([key, value]) => `${key}: ${value}`)
                  .join(", ")}
              </dd>
            </div>
          )}
        </dl>
        <p className="rounded-lg bg-muted/60 p-3 text-xs leading-relaxed text-muted-foreground">
          {model.note}
        </p>
      </CardContent>
    </Card>
  )
}

function AdminModels() {
  const { token } = useSession()
  const [models, setModels] = React.useState<ModelInfo[] | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [retry, setRetry] = React.useState(0)

  React.useEffect(() => {
    if (!token) return
    let active = true
    dashboardApi
      .models(token)
      .then((list) => {
        if (active) setModels(list)
      })
      .catch((err: Error) => {
        if (active) setError(err.message)
      })
    return () => {
      active = false
    }
  }, [token, retry])

  return (
    <DashboardShell
      title="Model info"
      description="Transparent record of the AI engines behind each screening."
    >
      {error && (
        <Alert variant="destructive">
          <Info />
          <AlertTitle>Could not load model info</AlertTitle>
          <AlertDescription>
            {error}{" "}
            <Button
              variant="link"
              className="h-auto p-0 text-destructive"
              onClick={() => setRetry((n) => n + 1)}
            >
              Try again
            </Button>
          </AlertDescription>
        </Alert>
      )}

      <Alert variant="default" className="bg-secondary/40">
        <Info />
        <AlertTitle>Honest model disclosure</AlertTitle>
        <AlertDescription>
          Production accuracy can only be trusted when every engine exposes
          its training data, validation metric, and weights status. If lists a
          model as &ldquo;not loaded&rdquo;, scans are stored but no AI
          assessment is generated until the backend is provisioned.
        </AlertDescription>
      </Alert>

      {models === null ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Loading model registry&hellip;
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {models.map((model) => (
            <ModelPanel key={model.name} model={model} />
          ))}
        </div>
      )}
    </DashboardShell>
  )
}

export default function AdminModelsPage() {
  return (
    <RequireRole roles={["admin"]}>
      <AdminModels />
    </RequireRole>
  )
}