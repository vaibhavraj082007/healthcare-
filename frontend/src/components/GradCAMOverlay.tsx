"use client";

interface GradCAMOverlayProps {
  /** URL to the Grad-CAM heatmap overlay image */
  gradcamUrl: string | null;
  /** URL to the original fundus image */
  originalUrl: string;
  /** Predicted class label */
  predictedClass?: string | null;
  /** Whether the model was trained */
  modelTrained: boolean;
}

/**
 * GradCAMOverlay — Displays the Grad-CAM explainability heatmap.
 *
 * Shows a side-by-side comparison of the original fundus image and the
 * Grad-CAM overlay highlighting regions most influential to the
 * classification decision.
 */
export function GradCAMOverlay({
  gradcamUrl,
  originalUrl,
  predictedClass,
  modelTrained,
}: GradCAMOverlayProps) {
  if (!modelTrained || !gradcamUrl) {
    return (
      <div
        className="glass-card"
        style={{
          textAlign: "center",
          padding: "40px",
          color: "var(--rs-text-muted)",
        }}
      >
        <p style={{ fontSize: "2rem", marginBottom: "8px" }}>🔍</p>
        <p style={{ fontWeight: 600 }}>Grad-CAM Unavailable</p>
        <p style={{ fontSize: "0.85rem", marginTop: "4px" }}>
          {!modelTrained
            ? "Model has not been trained — Grad-CAM requires a trained EfficientNet-B0."
            : "No heatmap generated for this analysis."}
        </p>
      </div>
    );
  }

  return (
    <div className="glass-card">
      <h3 style={{ fontSize: "1rem", fontWeight: 700, marginBottom: "12px" }}>
        Grad-CAM Explainability
        <span
          style={{
            fontSize: "0.75rem",
            color: "var(--rs-text-muted)",
            fontWeight: 400,
            marginLeft: "8px",
          }}
        >
          (Research Only)
        </span>
      </h3>
      <p style={{ fontSize: "0.8rem", color: "var(--rs-text-muted)", marginBottom: "16px" }}>
        Highlighted regions indicate areas most influential to the classification.
        This is for research interpretation only — not a clinical finding.
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px" }}>
        {/* Original */}
        <div>
          <p
            style={{
              fontSize: "0.8rem",
              color: "var(--rs-text-muted)",
              marginBottom: "6px",
              fontWeight: 600,
            }}
          >
            Original Fundus
          </p>
          <img
            src={originalUrl}
            alt="Original fundus"
            style={{
              width: "100%",
              borderRadius: "8px",
              border: "1px solid var(--rs-border)",
            }}
          />
        </div>

        {/* Grad-CAM Overlay */}
        <div>
          <p
            style={{
              fontSize: "0.8rem",
              color: "var(--rs-text-muted)",
              marginBottom: "6px",
              fontWeight: 600,
            }}
          >
            Grad-CAM Overlay
            {predictedClass && (
              <span style={{ color: "var(--rs-primary-light)", marginLeft: "6px" }}>
                → {predictedClass}
              </span>
            )}
          </p>
          <img
            src={gradcamUrl}
            alt="Grad-CAM heatmap overlay"
            style={{
              width: "100%",
              borderRadius: "8px",
              border: "1px solid var(--rs-border)",
            }}
          />
        </div>
      </div>

      {/* Color Legend */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "16px",
          marginTop: "12px",
          fontSize: "0.75rem",
          color: "var(--rs-text-muted)",
        }}
      >
        <span>Activation intensity:</span>
        <div
          style={{
            flex: 1,
            height: "8px",
            borderRadius: "4px",
            background: "linear-gradient(90deg, #0000ff, #00ffff, #00ff00, #ffff00, #ff0000)",
          }}
        />
        <span>Low → High</span>
      </div>
    </div>
  );
}
