"use client"

/**
 * Shared in-tab fundus / heatmap viewer (Phase-4-A fix).
 *
 * Used everywhere a scan image is shown: the patient dashboard, the doctor
 * case detail, the review queue and the ASHA worker dashboard. The thumbnail
 * opens a lightbox that supports wheel / pinch zoom, click-and-drag pan (via
 * react-zoom-pan-pinch) and, when a Grad-CAM heatmap exists for the scan, a
 * Fundus / Heatmap toggle so the reviewer can compare the two views side by
 * side in the same window instead of switching tabs.
 */

import * as React from "react"
import {
  TransformComponent,
  TransformWrapper,
  type ReactZoomPanPinchRef,
  useControls,
} from "react-zoom-pan-pinch"

import { Spinner } from "@/components/ui/spinner"
import { fetchGradcamBlobUrl, fetchScanBlobUrl } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Maximize2, Minimize2, RotateCcw, X, ZoomIn, ZoomOut } from "lucide-react"
import { cn } from "cn"

function LightboxControls({
  mode,
  hasHeatmap,
  onModeChange,
  onClose,
  onToggleFullscreen,
  isFullscreen,
}: {
  mode: "scan" | "heatmap"
  hasHeatmap: boolean
  onModeChange: (mode: "scan" | "heatmap") => void
  onClose: () => void
  onToggleFullscreen: () => void
  isFullscreen: boolean
}) {
  const { zoomIn, zoomOut, resetTransform } = useControls()

  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="flex items-center gap-1">
        {hasHeatmap && (
          <div className="flex items-center rounded-md bg-white/10 p-0.5">
            <button
              type="button"
              onClick={() => onModeChange("scan")}
              className={cn(
                "rounded px-3 py-1 text-xs font-semibold transition-colors",
                mode === "scan" ? "bg-white text-black" : "text-white/80 hover:text-white",
              )}
            >
              Fundus
            </button>
            <button
              type="button"
              onClick={() => onModeChange("heatmap")}
              className={cn(
                "rounded px-3 py-1 text-xs font-semibold transition-colors",
                mode === "heatmap" ? "bg-white text-black" : "text-white/80 hover:text-white",
              )}
            >
              Heatmap
            </button>
          </div>
        )}
        <button
          type="button"
          onClick={() => zoomIn()}
          aria-label="Zoom in"
          className="flex size-9 items-center justify-center rounded-md text-white/80 transition-colors hover:bg-white/10 hover:text-white"
        >
          <ZoomIn className="size-4" />
        </button>
        <button
          type="button"
          onClick={() => zoomOut()}
          aria-label="Zoom out"
          className="flex size-9 items-center justify-center rounded-md text-white/80 transition-colors hover:bg-white/10 hover:text-white"
        >
          <ZoomOut className="size-4" />
        </button>
        <button
          type="button"
          onClick={() => resetTransform()}
          aria-label="Reset zoom"
          title="Reset zoom"
          className="flex items-center gap-1 rounded-md px-2.5 text-xs font-medium text-white/80 transition-colors hover:bg-white/10 hover:text-white"
        >
          <RotateCcw className="size-4" />
          Reset
        </button>
        <button
          type="button"
          onClick={onToggleFullscreen}
          aria-label={isFullscreen ? "Exit fullscreen" : "Enter fullscreen"}
          className="flex size-9 items-center justify-center rounded-md text-white/80 transition-colors hover:bg-white/10 hover:text-white"
        >
          <Maximize2 className="size-4" />
        </button>
      </div>
      <button
        type="button"
        onClick={onClose}
        aria-label="Close viewer"
        className="flex size-9 items-center justify-center rounded-md text-white/80 transition-colors hover:bg-white/10 hover:text-white"
      >
        <X className="size-4" />
      </button>
    </div>
  )
}

export function ScanImageViewer({
  imageId,
  token,
  className,
  thumbnailClassName,
  showHeatmap = true,
  label = "Retina scan",
  defaultMode = "scan",
  thumbnailSource = "scan",
}: {
  imageId: string
  token: string
  className?: string
  thumbnailClassName?: string
  showHeatmap?: boolean
  label?: string
  defaultMode?: "scan" | "heatmap"
  thumbnailSource?: "scan" | "heatmap"
}) {
  const [scanUrl, setScanUrl] = React.useState<string | null>(null)
  const [heatmapUrl, setHeatmapUrl] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [heatmapLoading, setHeatmapLoading] = React.useState(false)
  const [open, setOpen] = React.useState(false)
  const [mode, setMode] = React.useState<"scan" | "heatmap">("scan")
  const [isFullscreen, setIsFullscreen] = React.useState(false)
  const lightboxRef = React.useRef<HTMLDivElement | null>(null)
  const wrapperRef = React.useRef<ReactZoomPanPinchRef | null>(null)

  React.useEffect(() => {
    let active = true
    setLoading(true)
    fetchScanBlobUrl(imageId, token)
      .then((url) => {
        if (active) setScanUrl(url)
      })
      .catch(() => {
        if (active) setScanUrl(null)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    if (showHeatmap) {
      setHeatmapLoading(true)
      fetchGradcamBlobUrl(imageId, token)
        .then((url) => {
          if (active) setHeatmapUrl(url)
        })
        .catch(() => {
          if (active) setHeatmapUrl(null)
        })
        .finally(() => {
          if (active) setHeatmapLoading(false)
        })
    }
    return () => {
      active = false
    }
  }, [imageId, token, showHeatmap])

  React.useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        if (document.fullscreenElement) {
          void document.exitFullscreen()
        } else {
          setOpen(false)
        }
      }
    }
    function onFsChange() {
      setIsFullscreen(!!document.fullscreenElement)
    }
    window.addEventListener("keydown", onKey)
    document.addEventListener("fullscreenchange", onFsChange)
    return () => {
      window.removeEventListener("keydown", onKey)
      document.removeEventListener("fullscreenchange", onFsChange)
    }
  }, [open])

  React.useEffect(() => {
    if (!open) return
    if (defaultMode === "heatmap") setMode("heatmap")
  }, [open, defaultMode])

  function toggleFullscreen() {
    const el = lightboxRef.current
    if (!el) return
    if (document.fullscreenElement) {
      void document.exitFullscreen()
    } else {
      void el.requestFullscreen()
    }
  }

  function openViewer() {
    setMode("scan")
    setOpen(true)
  }

  const activeUrl = mode === "heatmap" && heatmapUrl ? heatmapUrl : scanUrl
  const hasHeatmap = showHeatmap && heatmapUrl !== null

  // The thumbnail can preview the heatmap directly (Figure 2 of the medical
  // report), so a heatmap-preview thumbnail waits for the heatmap blob instead
  // of flashing the raw fundus photo first.
  const thumbShowsHeatmap = thumbnailSource === "heatmap" && heatmapUrl !== null
  const thumbPending = loading || (thumbnailSource === "heatmap" && heatmapLoading)

  if (thumbPending) {
    return (
      <div className={cn("flex items-center gap-2 text-sm text-muted-foreground", className)}>
        <Spinner size="sm" /> Loading image…
      </div>
    )
  }

  if (!scanUrl) return null

  return (
    <>
      <button
        type="button"
        onClick={openViewer}
        aria-label={`Open ${label} viewer`}
        className={cn(
          "relative block w-full cursor-zoom-in overflow-hidden rounded-lg border text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
          className,
        )}
      >
        {/* eslint-disable-next-line @next/next/no-img-element -- authenticated blob URL */}
        <img
          src={thumbShowsHeatmap ? heatmapUrl ?? scanUrl : scanUrl}
          alt={
            thumbShowsHeatmap
              ? `${label} — heatmap overlay — click to zoom`
              : `${label} — click to zoom`
          }
          className={cn("max-h-64 w-full rounded-lg object-cover", thumbnailClassName)}
        />
        <span className="absolute right-2 top-2 flex items-center gap-1 rounded-full bg-black/60 px-2 py-1 text-xs font-medium text-white backdrop-blur">
          <Maximize2 className="size-3" /> Zoom
        </span>
        {hasHeatmap && (
          <span className="absolute bottom-2 right-2 flex items-center gap-1 rounded-full bg-black/60 px-2 py-1 text-xs font-medium text-white backdrop-blur">
            {thumbShowsHeatmap ? "Heatmap" : "Fundus / Heatmap"}
          </span>
        )}
      </button>

      {open && (
        <div
          ref={lightboxRef}
          role="dialog"
          aria-modal="true"
          aria-label={`${label} viewer`}
          className="fixed inset-0 z-50 flex flex-col bg-black/90 backdrop-blur-sm"
          onClick={(e) => {
            if (e.target === e.currentTarget && !document.fullscreenElement) setOpen(false)
          }}
        >
          <TransformWrapper
            ref={wrapperRef}
            initialScale={1}
            minScale={0.5}
            maxScale={8}
            wheel={{ step: 0.18 }}
            doubleClick={{ mode: "toggle" }}
            limitToBounds
          >
            <div className="flex h-full flex-col gap-3 p-4">
              <LightboxControls
                mode={mode}
                hasHeatmap={hasHeatmap}
                onModeChange={(next) => setMode(next)}
                onClose={() => setOpen(false)}
                onToggleFullscreen={toggleFullscreen}
                isFullscreen={isFullscreen}
              />
              <div className="flex min-h-0 flex-1 items-center justify-center overflow-hidden">
                {activeUrl ? (
                  <TransformComponent
                    wrapperClass="h-full w-full flex items-center justify-center"
                    contentClass="!transform-origin-center"
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element -- blob URL */}
                    <img
                      src={activeUrl}
                      alt={`${label} — ${mode === "heatmap" ? "Grad-CAM heatmap" : "scan"}`}
                      className="max-h-full max-w-full rounded-lg bg-black shadow-xl"
                      draggable={false}
                    />
                  </TransformComponent>
                ) : (
                  <div className="flex items-center gap-2 text-sm text-white/70">
                    <Spinner size="sm" /> Loading…
                  </div>
                )}
              </div>
              <div className="flex flex-wrap items-center justify-center gap-2">
                <Badge tone="accent" className="capitalize">
                  {mode === "heatmap" ? "Grad-CAM heatmap" : label}
                </Badge>
                <Badge tone="success">Scroll / pinch to zoom · drag to pan</Badge>
                <Badge tone="destructive">Press Esc to close</Badge>
              </div>
            </div>
          </TransformWrapper>
        </div>
      )}
    </>
  )
}