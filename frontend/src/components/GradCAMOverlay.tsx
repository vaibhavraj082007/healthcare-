"use client";

import React, { useState } from "react";
import type { GradCAMExplanation, PreprocessingTransform } from "@/lib/types";

interface GradCAMOverlayProps {
  /** Grad-CAM explanation data structure */
  explanation?: GradCAMExplanation | null;
  /** Legacy/direct URL to the Grad-CAM heatmap overlay image */
  gradcamUrl?: string | null;
  /** URL to the original fundus image */
  originalUrl: string;
  /** Predicted class label */
  predictedClass?: string | null;
  /** Whether the model was trained */
  modelTrained: boolean;
}

/**
 * GradCAMOverlay — Displays the Gradient-weighted Class Activation Mapping (Grad-CAM)
 * explainability heatmap for the trained MATLAB classifier.
 *
 * Provides side-by-side inspection, opacity blending, coordinate transform provenance,
 * explanation-localization evaluation metrics, and clear disclaimers.
 */
export function GradCAMOverlay({
  explanation,
  gradcamUrl,
  originalUrl,
  predictedClass,
  modelTrained,
}: GradCAMOverlayProps) {
  const [opacity, setOpacity] = useState<number>(65);
  const [viewMode, setViewMode] = useState<"side-by-side" | "overlay">("side-by-side");
  const [zoomLevel, setZoomLevel] = useState<number>(1.0);

  const activeGradcamUrl = explanation?.gradcam_overlay_path || explanation?.gradcam_heatmap_path || gradcamUrl;
  const isAvailable = explanation ? explanation.status === "available" : (modelTrained && Boolean(activeGradcamUrl));
  const failureReason = explanation?.reason || (!modelTrained ? "EfficientNet-B0 classifier weights have not been trained on retinal data." : "Grad-CAM activations could not be extracted.");

  if (!isAvailable) {
    return (
      <div
        className="glass-card"
        style={{
          padding: "32px",
          border: "1px solid #f59e0b",
          background: "rgba(245, 158, 11, 0.05)",
          borderRadius: "12px",
        }}
      >
        <div style={{ display: "flex", alignItems: "flex-start", gap: "14px" }}>
          <span style={{ fontSize: "1.8rem" }}>⚠️</span>
          <div>
            <h3 style={{ fontSize: "1rem", fontWeight: 700, color: "#d97706", marginBottom: "4px" }}>
              Classifier Grad-CAM Unavailable
            </h3>
            <p style={{ fontSize: "0.85rem", color: "var(--rs-text)", marginBottom: "8px" }}>
              {failureReason}
            </p>
            <p style={{ fontSize: "0.78rem", color: "var(--rs-text-muted)", fontStyle: "italic" }}>
              RetinaShield strictly refuses to render synthetic or decorative heatmaps when true model activations are unavailable. Real explainability requires trained model weights and forward-backward activation passes.
            </p>
          </div>
        </div>
      </div>
    );
  }

  const targetClass = explanation?.target_class || predictedClass || "Predicted Class";
  const targetLayer = explanation?.target_layer || "top_conv";
  const algorithmVersion = explanation?.algorithm_version || "1.0.0-gradcam";
  const transform = explanation?.preprocessing_transform;

  return (
    <div className="glass-card" style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
      {/* Header with Title and Mode Controls */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "12px" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <h3 style={{ fontSize: "1.05rem", fontWeight: 700, color: "var(--rs-primary-dark)" }}>
              Classifier Grad-CAM Explainability
            </h3>
            <span
              style={{
                fontSize: "0.72rem",
                padding: "2px 8px",
                borderRadius: "4px",
                background: "rgba(59, 130, 246, 0.12)",
                color: "#2563eb",
                fontWeight: 600,
              }}
            >
              {algorithmVersion}
            </span>
          </div>
          <p style={{ fontSize: "0.8rem", color: "var(--rs-text-muted)", marginTop: "2px" }}>
            Explaining output activations for: <strong style={{ color: "var(--rs-text)" }}>{targetClass}</strong> (Layer: <code>{targetLayer}</code>)
          </p>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          {/* View Mode Switcher */}
          <div style={{ display: "inline-flex", background: "var(--rs-bg-elevated)", borderRadius: "6px", padding: "2px", border: "1px solid var(--rs-border)" }}>
            <button
              type="button"
              onClick={() => setViewMode("side-by-side")}
              style={{
                padding: "4px 10px",
                fontSize: "0.75rem",
                fontWeight: viewMode === "side-by-side" ? 600 : 400,
                background: viewMode === "side-by-side" ? "var(--rs-bg-card)" : "transparent",
                color: viewMode === "side-by-side" ? "var(--rs-primary-dark)" : "var(--rs-text-muted)",
                border: "none",
                borderRadius: "4px",
                cursor: "pointer",
              }}
            >
              Side-by-Side
            </button>
            <button
              type="button"
              onClick={() => setViewMode("overlay")}
              style={{
                padding: "4px 10px",
                fontSize: "0.75rem",
                fontWeight: viewMode === "overlay" ? 600 : 400,
                background: viewMode === "overlay" ? "var(--rs-bg-card)" : "transparent",
                color: viewMode === "overlay" ? "var(--rs-primary-dark)" : "var(--rs-text-muted)",
                border: "none",
                borderRadius: "4px",
                cursor: "pointer",
              }}
            >
              Blended Overlay
            </button>
          </div>

          {/* Zoom controls */}
          <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
            <button
              type="button"
              onClick={() => setZoomLevel((z) => Math.max(0.75, +(z - 0.25).toFixed(2)))}
              style={{ padding: "3px 8px", fontSize: "0.75rem", cursor: "pointer", border: "1px solid var(--rs-border)", borderRadius: "4px", background: "var(--rs-bg-card)" }}
            >
              −
            </button>
            <span style={{ fontSize: "0.75rem", minWidth: "36px", textAlign: "center" }}>{Math.round(zoomLevel * 100)}%</span>
            <button
              type="button"
              onClick={() => setZoomLevel((z) => Math.min(2.5, +(z + 0.25).toFixed(2)))}
              style={{ padding: "3px 8px", fontSize: "0.75rem", cursor: "pointer", border: "1px solid var(--rs-border)", borderRadius: "4px", background: "var(--rs-bg-card)" }}
            >
              +
            </button>
          </div>
        </div>
      </div>

      {/* Opacity slider for Blended mode */}
      {viewMode === "overlay" && (
        <div style={{ display: "flex", alignItems: "center", gap: "10px", fontSize: "0.8rem", color: "var(--rs-text-muted)" }}>
          <span>Heatmap Opacity:</span>
          <input
            type="range"
            min="10"
            max="100"
            value={opacity}
            onChange={(e) => setOpacity(Number(e.target.value))}
            style={{ width: "120px", accentColor: "#f59e0b", cursor: "pointer" }}
          />
          <span style={{ fontWeight: 600 }}>{opacity}%</span>
        </div>
      )}

      {/* Main Image Visualization Canvas */}
      <div
        style={{
          background: "#0a0f1d",
          borderRadius: "8px",
          padding: "16px",
          overflow: "auto",
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          minHeight: "360px",
        }}
      >
        <div
          style={{
            transform: `scale(${zoomLevel})`,
            transformOrigin: "center center",
            transition: "transform 0.15s ease-out",
            display: "flex",
            justifyContent: "center",
            width: "100%",
          }}
        >
          {viewMode === "side-by-side" ? (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", width: "100%", maxWidth: "800px" }}>
              <div>
                <p style={{ fontSize: "0.75rem", color: "#94a3b8", marginBottom: "6px", fontWeight: 600 }}>
                  Original Fundus
                </p>
                <img
                  src={originalUrl}
                  alt="Original fundus"
                  style={{
                    width: "100%",
                    borderRadius: "6px",
                    border: "1px solid #334155",
                    display: "block",
                  }}
                />
              </div>
              <div>
                <p style={{ fontSize: "0.75rem", color: "#fbbf24", marginBottom: "6px", fontWeight: 600 }}>
                  Grad-CAM Activation Heatmap
                </p>
                <img
                  src={activeGradcamUrl || ""}
                  alt="Grad-CAM activation heatmap"
                  style={{
                    width: "100%",
                    borderRadius: "6px",
                    border: "1px solid #334155",
                    display: "block",
                  }}
                />
              </div>
            </div>
          ) : (
            <div style={{ position: "relative", display: "inline-block", maxWidth: "600px" }}>
              <img
                src={originalUrl}
                alt="Original fundus"
                style={{
                  display: "block",
                  width: "100%",
                  borderRadius: "6px",
                }}
              />
              <img
                src={explanation?.gradcam_heatmap_path || activeGradcamUrl || ""}
                alt="Grad-CAM overlay"
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  width: "100%",
                  height: "100%",
                  borderRadius: "6px",
                  opacity: opacity / 100,
                  mixBlendMode: "screen",
                  pointerEvents: "none",
                }}
              />
            </div>
          )}
        </div>
      </div>

      {/* Jet Colormap Scale Legend */}
      <div style={{ display: "flex", alignItems: "center", gap: "12px", fontSize: "0.75rem", color: "var(--rs-text-muted)" }}>
        <span style={{ fontWeight: 600, color: "var(--rs-text)" }}>Model Influence:</span>
        <span>Low (0.0)</span>
        <div
          style={{
            flex: 1,
            maxWidth: "200px",
            height: "8px",
            borderRadius: "4px",
            background: "linear-gradient(90deg, #00008f, #0000ff, #007fff, #00ffff, #7fff7f, #ffff00, #ff7f00, #ff0000, #7f0000)",
          }}
        />
        <span style={{ color: "#ef4444", fontWeight: 600 }}>High (1.0)</span>
      </div>

      {/* Provenance & Coordinate Transformation Metadata */}
      <div
        style={{
          background: "var(--rs-bg-elevated)",
          border: "1px solid var(--rs-border)",
          borderRadius: "8px",
          padding: "10px 14px",
          fontSize: "0.75rem",
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
          gap: "10px",
        }}
      >
        <div>
          <span style={{ color: "var(--rs-text-muted)" }}>Target Conv Layer:</span>
          <div style={{ fontWeight: 600, color: "var(--rs-text)" }}>{targetLayer}</div>
        </div>
        <div>
          <span style={{ color: "var(--rs-text-muted)" }}>Explained Class:</span>
          <div style={{ fontWeight: 600, color: "var(--rs-primary-dark)" }}>{targetClass}</div>
        </div>
        {transform && (
          <>
            <div>
              <span style={{ color: "var(--rs-text-muted)" }}>Model Input Resolution:</span>
              <div style={{ fontWeight: 600, color: "var(--rs-text)" }}>
                {transform.model_input_size ? `${transform.model_input_size[0]}×${transform.model_input_size[1]} px` : "224×224 px"}
              </div>
            </div>
            <div>
              <span style={{ color: "var(--rs-text-muted)" }}>Original Image Scale:</span>
              <div style={{ fontWeight: 600, color: "var(--rs-text)" }}>
                {transform.original_size ? `${transform.original_size[0]}×${transform.original_size[1]} px` : "Full resolution"}
              </div>
            </div>
          </>
        )}
      </div>

      {/* Explanation-Localization Evaluation (if expert annotations provided) */}
      {(explanation?.pointing_game_hit !== undefined && explanation?.pointing_game_hit !== null) && (
        <div
          style={{
            background: "rgba(16, 185, 129, 0.06)",
            border: "1px solid rgba(16, 185, 129, 0.25)",
            borderRadius: "8px",
            padding: "10px 14px",
            fontSize: "0.78rem",
          }}
        >
          <div style={{ fontWeight: 700, color: "var(--rs-success)", marginBottom: "4px" }}>
            Explanation-Localization Evaluation against Expert Masks
          </div>
          <div style={{ display: "flex", gap: "16px", flexWrap: "wrap", color: "var(--rs-text)" }}>
            <div>
              Pointing Game:{" "}
              <strong style={{ color: explanation.pointing_game_hit ? "#16a34a" : "#dc2626" }}>
                {explanation.pointing_game_hit ? "HIT (Peak inside lesion mask)" : "MISS"}
              </strong>
            </div>
            {explanation.expert_iou !== null && explanation.expert_iou !== undefined && (
              <div>
                Thresholded IoU: <strong>{(explanation.expert_iou * 100).toFixed(1)}%</strong>
              </div>
            )}
            {explanation.energy_pointing_game !== null && explanation.energy_pointing_game !== undefined && (
              <div>
                Energy Pointing Fraction: <strong>{(explanation.energy_pointing_game * 100).toFixed(1)}%</strong>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Mandatory Medical Disclaimer Banner */}
      <div
        style={{
          borderLeft: "3px solid #f59e0b",
          paddingLeft: "10px",
          fontSize: "0.74rem",
          color: "var(--rs-text-muted)",
          lineHeight: 1.4,
        }}
      >
        <strong>Mandatory Clinical Interpretation Notice:</strong> Grad-CAM highlights image features that maximally activated the neural network during its decision process. It does <em>not</em> represent confirmed anatomical lesions, clinician-validated pathology, or proof of diagnostic accuracy.
      </div>
    </div>
  );
}
