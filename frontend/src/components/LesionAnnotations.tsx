"use client";

import type { LesionDetection } from "@/lib/types";

interface LesionAnnotationsProps {
  detections: LesionDetection[];
  modelTrained: boolean;
}

const LESION_INFO: Record<string, { label: string; color: string; description: string }> = {
  microaneurysm: {
    label: "Microaneurysm",
    color: "#ef4444",
    description: "Small round dot hemorrhages from weakened capillary walls",
  },
  hemorrhage: {
    label: "Hemorrhage",
    color: "#dc2626",
    description: "Bleeding from damaged retinal blood vessels",
  },
  hard_exudate: {
    label: "Hard Exudate",
    color: "#eab308",
    description: "Lipid and protein deposits from leaking vessels",
  },
  soft_exudate: {
    label: "Soft Exudate",
    color: "#f97316",
    description: "Cotton-wool spots from nerve fiber layer infarction",
  },
  neovascularization: {
    label: "Neovascularization",
    color: "#a855f7",
    description: "Abnormal new blood vessel growth (indicates proliferative DR)",
  },
};

/**
 * LesionAnnotations — Displays a summary of detected lesions.
 *
 * Groups detections by type and shows counts and confidence ranges.
 */
export function LesionAnnotations({ detections, modelTrained }: LesionAnnotationsProps) {
  if (!modelTrained) {
    return (
      <div
        className="glass-card"
        style={{ color: "var(--rs-text-muted)", textAlign: "center", padding: "30px" }}
      >
        <p style={{ fontWeight: 600 }}>YOLOv8 Model Not Trained</p>
        <p style={{ fontSize: "0.85rem", marginTop: "4px" }}>
          Train on a lesion-annotated dataset (e.g., IDRiD) to enable detection.
        </p>
      </div>
    );
  }

  if (detections.length === 0) {
    return (
      <div
        className="glass-card"
        style={{ color: "var(--rs-text-muted)", textAlign: "center", padding: "30px" }}
      >
        <p style={{ fontWeight: 600 }}>No Lesions Detected</p>
        <p style={{ fontSize: "0.85rem", marginTop: "4px" }}>
          No DR-related lesions were detected above the confidence threshold.
        </p>
      </div>
    );
  }

  // Group by type
  const grouped = detections.reduce<Record<string, LesionDetection[]>>((acc, d) => {
    if (!acc[d.lesion_type]) acc[d.lesion_type] = [];
    acc[d.lesion_type].push(d);
    return acc;
  }, {});

  return (
    <div className="glass-card">
      <h3 style={{ fontSize: "1rem", fontWeight: 700, marginBottom: "4px" }}>
        Lesion Detection
        <span
          style={{
            fontSize: "0.75rem",
            color: "var(--rs-text-muted)",
            fontWeight: 400,
            marginLeft: "8px",
          }}
        >
          YOLOv8 • {detections.length} found
        </span>
      </h3>
      <p style={{ fontSize: "0.8rem", color: "var(--rs-text-muted)", marginBottom: "16px" }}>
        Research screening — not a clinical finding
      </p>

      <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
        {Object.entries(grouped).map(([type, items]) => {
          const info = LESION_INFO[type] || { label: type, color: "#94a3b8", description: "" };
          const minConf = Math.min(...items.map((d) => d.confidence));
          const maxConf = Math.max(...items.map((d) => d.confidence));

          return (
            <div
              key={type}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "10px 14px",
                background: `${info.color}10`,
                border: `1px solid ${info.color}30`,
                borderRadius: "10px",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                <span
                  style={{
                    width: "10px",
                    height: "10px",
                    borderRadius: "3px",
                    backgroundColor: info.color,
                    display: "inline-block",
                  }}
                />
                <div>
                  <span style={{ fontWeight: 600, fontSize: "0.9rem" }}>
                    {info.label}
                  </span>
                  <p style={{ fontSize: "0.75rem", color: "var(--rs-text-muted)", marginTop: "2px" }}>
                    {info.description}
                  </p>
                </div>
              </div>
              <div style={{ textAlign: "right" }}>
                <span style={{ fontWeight: 700, fontSize: "1.1rem", color: info.color }}>
                  {items.length}
                </span>
                <p style={{ fontSize: "0.7rem", color: "var(--rs-text-muted)" }}>
                  {(minConf * 100).toFixed(0)}–{(maxConf * 100).toFixed(0)}% conf
                </p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
