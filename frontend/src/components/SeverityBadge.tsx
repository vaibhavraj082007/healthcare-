"use client";

import { DR_SEVERITY_CODES } from "@/lib/types";

interface SeverityBadgeProps {
  grade: number | null;
  label: string | null;
  modelTrained: boolean;
}

/**
 * SeverityBadge — Displays the DR severity grade with color coding.
 *
 * Clearly indicates when the model is untrained to prevent misinterpretation.
 */
export function SeverityBadge({ grade, label, modelTrained }: SeverityBadgeProps) {
  if (!modelTrained || grade === null || grade < 0) {
    return (
      <span className="severity-badge untrained">
        <span style={{ fontSize: "0.7rem" }}>◌</span>
        Untrained
      </span>
    );
  }

  const code = DR_SEVERITY_CODES[grade];
  const gradeClass = `grade-${grade}`;

  return (
    <span className={`severity-badge ${gradeClass}`}>
      <span
        style={{
          width: "8px",
          height: "8px",
          borderRadius: "50%",
          backgroundColor: code?.color_hex || "#94a3b8",
          display: "inline-block",
        }}
      />
      {label || code?.label || `Grade ${grade}`}
    </span>
  );
}
