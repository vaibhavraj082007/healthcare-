"use client";

import React, { useState, useEffect } from "react";
import {
  monitoringApi,
  screeningsApi,
  OperationalMetrics,
  ShiftMetrics,
  InteropStatus,
  FHIRBundleExport,
  ExchangeTestResult,
} from "@/lib/api";
import type { ScreeningSummary } from "@/lib/types";

export default function MonitoringDashboardPage() {
  const [activeTab, setActiveTab] = useState<"operational" | "shifts" | "interop">("operational");
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Data states
  const [operational, setOperational] = useState<OperationalMetrics | null>(null);
  const [shifts, setShifts] = useState<ShiftMetrics | null>(null);
  const [interop, setInterop] = useState<InteropStatus | null>(null);
  const [recentScreenings, setRecentScreenings] = useState<ScreeningSummary[]>([]);

  // Interop export states
  const [selectedScreeningId, setSelectedScreeningId] = useState<string>("");
  const [exportedBundle, setExportedBundle] = useState<FHIRBundleExport | null>(null);
  const [exportLoading, setExportLoading] = useState<boolean>(false);
  const [exportError, setExportError] = useState<string | null>(null);

  // Exchange test states
  const [exchangeTestResult, setExchangeTestResult] = useState<ExchangeTestResult | null>(null);
  const [testLoading, setTestLoading] = useState<boolean>(false);

  // Filters
  const [daysLookback, setDaysLookback] = useState<number>(30);
  const [currentShiftDays, setCurrentShiftDays] = useState<number>(7);
  const [baselineShiftDays, setBaselineShiftDays] = useState<number>(30);

  useEffect(() => {
    loadAllData();
  }, [daysLookback, currentShiftDays, baselineShiftDays]);

  async function loadAllData() {
    setLoading(true);
    setError(null);
    try {
      const [opData, shiftData, interopData, scList] = await Promise.all([
        monitoringApi.getOperational({ days: daysLookback }),
        monitoringApi.getShifts({ current_days: currentShiftDays, baseline_days: baselineShiftDays }),
        monitoringApi.getInteropStatus(),
        screeningsApi.list({ limit: 10 }).catch(() => []),
      ]);
      setOperational(opData);
      setShifts(shiftData);
      setInterop(interopData);
      setRecentScreenings(scList || []);
      if (scList && scList.length > 0 && !selectedScreeningId) {
        setSelectedScreeningId(scList[0].id);
      }
    } catch (err: any) {
      setError(err.message || "Failed to load monitoring metrics");
    } finally {
      setLoading(false);
    }
  }

  async function handleExportFHIR() {
    if (!selectedScreeningId) return;
    setExportLoading(true);
    setExportError(null);
    try {
      const res = await monitoringApi.exportFHIR(selectedScreeningId);
      setExportedBundle(res);
    } catch (err: any) {
      setExportError(err.message || "Failed to export FHIR Document Bundle");
    } finally {
      setExportLoading(false);
    }
  }

  async function handleTestExchange() {
    setTestLoading(true);
    try {
      const res = await monitoringApi.testExchange();
      setExchangeTestResult(res);
    } catch (err: any) {
      alert(err.message || "Exchange readiness test failed");
    } finally {
      setTestLoading(false);
    }
  }

  function downloadJSON(data: any, filename: string) {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  return (
    <div style={{ paddingBottom: "48px" }}>
      {/* Page Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "20px" }}>
        <div>
          <h1 style={{ fontSize: "1.8rem", fontWeight: 800, margin: "0 0 6px 0", color: "var(--rs-text)" }}>
            Operational Monitoring & Clinical Interoperability
          </h1>
          <p style={{ color: "var(--rs-text-muted)", margin: 0, fontSize: "0.95rem" }}>
            Real-time surveillance of screening volume, review backlogs, pipeline latency, data distribution shifts, and HL7 FHIR R4 exports.
          </p>
        </div>
        <button
          onClick={loadAllData}
          className="btn-secondary"
          style={{ padding: "8px 16px", display: "flex", alignItems: "center", gap: "8px" }}
          disabled={loading}
        >
          <span>🔄</span> {loading ? "Refreshing..." : "Refresh Metrics"}
        </button>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", gap: "8px", borderBottom: "1px solid var(--rs-border)", marginBottom: "24px" }}>
        <button
          onClick={() => setActiveTab("operational")}
          style={{
            padding: "10px 20px",
            background: "none",
            border: "none",
            borderBottom: activeTab === "operational" ? "3px solid #14b8a6" : "3px solid transparent",
            color: activeTab === "operational" ? "#14b8a6" : "var(--rs-text-muted)",
            fontWeight: activeTab === "operational" ? 700 : 500,
            fontSize: "1rem",
            cursor: "pointer",
          }}
        >
          📊 Operational Metrics
        </button>
        <button
          onClick={() => setActiveTab("shifts")}
          style={{
            padding: "10px 20px",
            background: "none",
            border: "none",
            borderBottom: activeTab === "shifts" ? "3px solid #14b8a6" : "3px solid transparent",
            color: activeTab === "shifts" ? "#14b8a6" : "var(--rs-text-muted)",
            fontWeight: activeTab === "shifts" ? 700 : 500,
            fontSize: "1rem",
            cursor: "pointer",
          }}
        >
          📉 Shift Surveillance
        </button>
        <button
          onClick={() => setActiveTab("interop")}
          style={{
            padding: "10px 20px",
            background: "none",
            border: "none",
            borderBottom: activeTab === "interop" ? "3px solid #14b8a6" : "3px solid transparent",
            color: activeTab === "interop" ? "#14b8a6" : "var(--rs-text-muted)",
            fontWeight: activeTab === "interop" ? 700 : 500,
            fontSize: "1rem",
            cursor: "pointer",
          }}
        >
          🌐 ABDM & FHIR R4 Export
        </button>
      </div>

      {error && (
        <div style={{ padding: "16px", background: "rgba(239, 68, 68, 0.1)", border: "1px solid #ef4444", borderRadius: "8px", color: "#ef4444", marginBottom: "24px" }}>
          <strong>Error:</strong> {error}
        </div>
      )}

      {/* =================================================================== */}
      {/* TAB 1: OPERATIONAL METRICS */}
      {/* =================================================================== */}
      {activeTab === "operational" && operational && (
        <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
          {/* Architectural Separation Banner */}
          <div
            style={{
              padding: "16px 20px",
              background: "rgba(20, 184, 166, 0.08)",
              border: "1px solid rgba(20, 184, 166, 0.3)",
              borderRadius: "10px",
              display: "flex",
              gap: "14px",
              alignItems: "flex-start",
            }}
          >
            <span style={{ fontSize: "1.5rem" }}>🛡️</span>
            <div>
              <strong style={{ color: "#14b8a6", fontSize: "0.95rem" }}>
                ARCHITECTURAL SEPARATION OF OPERATIONAL MONITORING & CLINICAL ACCURACY
              </strong>
              <p style={{ margin: "4px 0 0 0", color: "var(--rs-text-secondary)", fontSize: "0.88rem", lineHeight: 1.5 }}>
                {operational.clinical_accuracy_separation_disclaimer}
              </p>
            </div>
          </div>

          {/* Privacy Notice Pill */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span
              style={{
                fontSize: "0.82rem",
                padding: "4px 12px",
                background: "rgba(124, 58, 237, 0.1)",
                color: "#a78bfa",
                border: "1px solid rgba(124, 58, 237, 0.25)",
                borderRadius: "20px",
              }}
            >
              🔒 Privacy-Preserving Aggregation: Groups with &lt; {operational.privacy_suppression_threshold} cases are suppressed to protect patient identity (DPDP Act 2023).
            </span>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <label style={{ fontSize: "0.88rem", color: "var(--rs-text-muted)" }}>Lookback Window:</label>
              <select
                value={daysLookback}
                onChange={(e) => setDaysLookback(Number(e.target.value))}
                style={{
                  background: "var(--rs-bg-secondary)",
                  color: "var(--rs-text)",
                  border: "1px solid var(--rs-border)",
                  borderRadius: "6px",
                  padding: "4px 8px",
                  fontSize: "0.88rem",
                }}
              >
                <option value={7}>Last 7 Days</option>
                <option value={30}>Last 30 Days</option>
                <option value={90}>Last 90 Days</option>
              </select>
            </div>
          </div>

          {/* Primary Metrics Grid */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "16px" }}>
            {/* Volume Card */}
            <div className="card" style={{ padding: "20px" }}>
              <span style={{ fontSize: "0.82rem", color: "var(--rs-text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                Screening Volume
              </span>
              <div style={{ fontSize: "2rem", fontWeight: 800, margin: "8px 0 4px 0", color: "#38bdf8" }}>
                {operational.screening_volume.total_screenings}
              </div>
              <div style={{ fontSize: "0.82rem", color: "var(--rs-text-muted)" }}>
                24h: <strong>{operational.screening_volume.last_24h}</strong> | 7d: <strong>{operational.screening_volume.last_7d}</strong>
              </div>
            </div>

            {/* Ungradeable Rate Card */}
            <div className="card" style={{ padding: "20px" }}>
              <span style={{ fontSize: "0.82rem", color: "var(--rs-text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                Ungradeable Rate
              </span>
              <div style={{ fontSize: "2rem", fontWeight: 800, margin: "8px 0 4px 0", color: operational.ungradeable_rates.ungradeable_rate_pct > 15 ? "#ef4444" : "#14b8a6" }}>
                {operational.ungradeable_rates.ungradeable_rate_pct}%
              </div>
              <div style={{ fontSize: "0.82rem", color: "var(--rs-text-muted)" }}>
                AI: {operational.ungradeable_rates.ai_ungradeable_count} ({operational.ungradeable_rates.ai_ungradeable_pct}%) | Clinician: {operational.ungradeable_rates.clinician_ungradeable_count}
              </div>
            </div>

            {/* Backlog Card */}
            <div className="card" style={{ padding: "20px" }}>
              <span style={{ fontSize: "0.82rem", color: "var(--rs-text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                Review Backlog
              </span>
              <div style={{ fontSize: "2rem", fontWeight: 800, margin: "8px 0 4px 0", color: operational.review_backlog.total_backlog > 10 ? "#f59e0b" : "#38bdf8" }}>
                {operational.review_backlog.total_backlog}
              </div>
              <div style={{ fontSize: "0.82rem", color: "var(--rs-text-muted)" }}>
                Awaiting: <strong>{operational.review_backlog.awaiting_review_count}</strong> | Draft: <strong>{operational.review_backlog.draft_review_count}</strong>
              </div>
            </div>

            {/* Failures Card */}
            <div className="card" style={{ padding: "20px" }}>
              <span style={{ fontSize: "0.82rem", color: "var(--rs-text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                Processing Failures
              </span>
              <div style={{ fontSize: "2rem", fontWeight: 800, margin: "8px 0 4px 0", color: operational.processing_failures.failed_jobs > 0 ? "#ef4444" : "#10b981" }}>
                {operational.processing_failures.failed_jobs}
              </div>
              <div style={{ fontSize: "0.82rem", color: "var(--rs-text-muted)" }}>
                Failure Rate: <strong>{operational.processing_failures.failure_rate_pct}%</strong> of {operational.processing_failures.total_jobs} jobs
              </div>
            </div>

            {/* Sync Failures Card */}
            <div className="card" style={{ padding: "20px" }}>
              <span style={{ fontSize: "0.82rem", color: "var(--rs-text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                Sync Conflicts
              </span>
              <div style={{ fontSize: "2rem", fontWeight: 800, margin: "8px 0 4px 0", color: operational.synchronization_failures.sync_conflicts_unresolved > 0 ? "#f59e0b" : "#10b981" }}>
                {operational.synchronization_failures.sync_conflicts_unresolved}
              </div>
              <div style={{ fontSize: "0.82rem", color: "var(--rs-text-muted)" }}>
                Pending Sync: <strong>{operational.synchronization_failures.pending_sync_screenings}</strong> | Conflicts: <strong>{operational.synchronization_failures.sync_conflicts_total}</strong>
              </div>
            </div>

            {/* Latency Card */}
            <div className="card" style={{ padding: "20px" }}>
              <span style={{ fontSize: "0.82rem", color: "var(--rs-text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                Latency (p95 / Mean)
              </span>
              <div style={{ fontSize: "2rem", fontWeight: 800, margin: "8px 0 4px 0", color: "#a78bfa" }}>
                {operational.latency.p95_seconds !== null ? `${operational.latency.p95_seconds}s` : "N/A"}
              </div>
              <div style={{ fontSize: "0.82rem", color: "var(--rs-text-muted)" }}>
                Mean: {operational.latency.mean_seconds !== null ? `${operational.latency.mean_seconds}s` : "N/A"} | Median: {operational.latency.median_seconds !== null ? `${operational.latency.median_seconds}s` : "N/A"}
              </div>
            </div>
          </div>

          {/* Two-Column Deep-Dive */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(400px, 1fr))", gap: "20px" }}>
            {/* Backlog Age & Urgency */}
            <div className="card" style={{ padding: "20px" }}>
              <h3 style={{ fontSize: "1.1rem", margin: "0 0 16px 0", color: "var(--rs-text)" }}>
                Review Backlog Aging & Urgency
              </h3>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px" }}>
                <div>
                  <div style={{ fontSize: "0.82rem", color: "var(--rs-text-muted)", marginBottom: "8px" }}>Age Distribution:</div>
                  <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.88rem" }}>
                      <span>&lt; 24 hours</span>
                      <strong style={{ color: "#10b981" }}>{operational.review_backlog.age_distribution["under_24h"] || 0}</strong>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.88rem" }}>
                      <span>24 – 72 hours</span>
                      <strong style={{ color: "#f59e0b" }}>{operational.review_backlog.age_distribution["between_24_72h"] || 0}</strong>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.88rem" }}>
                      <span>&gt; 72 hours</span>
                      <strong style={{ color: "#ef4444" }}>{operational.review_backlog.age_distribution["over_72h"] || 0}</strong>
                    </div>
                  </div>
                </div>

                <div>
                  <div style={{ fontSize: "0.82rem", color: "var(--rs-text-muted)", marginBottom: "8px" }}>Provisional Urgency:</div>
                  <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.88rem" }}>
                      <span>Urgent</span>
                      <strong style={{ color: "#ef4444" }}>{operational.review_backlog.urgency_distribution["urgent"] || 0}</strong>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.88rem" }}>
                      <span>Priority</span>
                      <strong style={{ color: "#f59e0b" }}>{operational.review_backlog.urgency_distribution["priority"] || 0}</strong>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.88rem" }}>
                      <span>Routine</span>
                      <strong style={{ color: "#38bdf8" }}>{operational.review_backlog.urgency_distribution["routine"] || 0}</strong>
                    </div>
                  </div>
                </div>
              </div>
              {operational.review_backlog.oldest_pending_hours !== null && (
                <div style={{ marginTop: "14px", padding: "8px 12px", background: "rgba(245, 158, 11, 0.1)", borderRadius: "6px", fontSize: "0.82rem", color: "#f59e0b" }}>
                  ⏳ Oldest pending unreviewed encounter: <strong>{operational.review_backlog.oldest_pending_hours} hours</strong>
                </div>
              )}
            </div>

            {/* Pipeline Stage Latency */}
            <div className="card" style={{ padding: "20px" }}>
              <h3 style={{ fontSize: "1.1rem", margin: "0 0 16px 0", color: "var(--rs-text)" }}>
                Pipeline Stage Latencies
              </h3>
              {Object.keys(operational.latency.stage_breakdown_mean_seconds).length > 0 ? (
                <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                  {Object.entries(operational.latency.stage_breakdown_mean_seconds).map(([stage, dur]) => (
                    <div key={stage}>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.85rem", marginBottom: "4px" }}>
                        <span style={{ textTransform: "capitalize" }}>{stage.replace(/_/g, " ")}</span>
                        <strong>{dur}s</strong>
                      </div>
                      <div style={{ background: "rgba(255,255,255,0.08)", height: "6px", borderRadius: "3px", overflow: "hidden" }}>
                        <div
                          style={{
                            background: "linear-gradient(90deg, #14b8a6, #38bdf8)",
                            height: "100%",
                            width: `${Math.min(100, (dur / 15) * 100)}%`,
                          }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p style={{ color: "var(--rs-text-muted)", fontSize: "0.88rem" }}>
                  Detailed stage timings available once background jobs complete. Overall mean duration: {operational.latency.mean_seconds || 0}s.
                </p>
              )}
            </div>
          </div>

          {/* Model Version Usage & Facility Volume */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(400px, 1fr))", gap: "20px" }}>
            {/* Model Versions */}
            <div className="card" style={{ padding: "20px" }}>
              <h3 style={{ fontSize: "1.1rem", margin: "0 0 16px 0", color: "var(--rs-text)" }}>
                Model-Version Usage
              </h3>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.88rem" }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid var(--rs-border)", textAlign: "left", color: "var(--rs-text-muted)" }}>
                    <th style={{ paddingBottom: "8px" }}>Model</th>
                    <th style={{ paddingBottom: "8px" }}>Version</th>
                    <th style={{ paddingBottom: "8px" }}>Runs</th>
                    <th style={{ paddingBottom: "8px" }}>Share</th>
                    <th style={{ paddingBottom: "8px" }}>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {operational.model_version_usage.map((m, idx) => (
                    <tr key={idx} style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                      <td style={{ padding: "8px 0", fontWeight: 600 }}>{m.model_name}</td>
                      <td style={{ padding: "8px 0", color: "var(--rs-text-muted)" }}>{m.model_version}</td>
                      <td style={{ padding: "8px 0" }}>{m.runs_count}</td>
                      <td style={{ padding: "8px 0" }}>{m.percentage}%</td>
                      <td style={{ padding: "8px 0" }}>
                        <span
                          style={{
                            fontSize: "0.75rem",
                            padding: "2px 8px",
                            borderRadius: "12px",
                            background: m.model_trained ? "rgba(16, 185, 129, 0.15)" : "rgba(245, 158, 11, 0.15)",
                            color: m.model_trained ? "#10b981" : "#f59e0b",
                          }}
                        >
                          {m.model_trained ? "Trained" : "Fallback"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Volume by Facility (with suppression) */}
            <div className="card" style={{ padding: "20px" }}>
              <h3 style={{ fontSize: "1.1rem", margin: "0 0 16px 0", color: "var(--rs-text)" }}>
                Facility Volume Breakdown
              </h3>
              <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                {operational.screening_volume.by_facility.map((fac, idx) => (
                  <div
                    key={idx}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      padding: "8px 12px",
                      background: "var(--rs-bg-secondary)",
                      borderRadius: "6px",
                      fontSize: "0.88rem",
                    }}
                  >
                    <span>{fac.category}</span>
                    <span
                      style={{
                        fontWeight: 700,
                        color: fac.is_suppressed ? "#a78bfa" : "var(--rs-text)",
                      }}
                    >
                      {fac.display_count} {fac.is_suppressed && "(Suppressed)"}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* =================================================================== */}
      {/* TAB 2: SHIFT SURVEILLANCE */}
      {/* =================================================================== */}
      {activeTab === "shifts" && shifts && (
        <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
          {/* Regulatory Safety Warning */}
          <div
            style={{
              padding: "16px 20px",
              background: "rgba(245, 158, 11, 0.08)",
              border: "1px solid rgba(245, 158, 11, 0.3)",
              borderRadius: "10px",
              display: "flex",
              gap: "14px",
              alignItems: "flex-start",
            }}
          >
            <span style={{ fontSize: "1.5rem" }}>⚠️</span>
            <div>
              <strong style={{ color: "#f59e0b", fontSize: "0.95rem" }}>
                REGULATORY & CLINICAL SAFETY MANDATE — NO AUTOMATED RETRAINING
              </strong>
              <p style={{ margin: "4px 0 0 0", color: "var(--rs-text-secondary)", fontSize: "0.88rem", lineHeight: 1.5 }}>
                {shifts.regulatory_safety_notice}
              </p>
            </div>
          </div>

          {/* Cohort Window Bar */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div style={{ fontSize: "0.9rem", color: "var(--rs-text-muted)" }}>
              Comparing <strong>Current Cohort ({shifts.current_window_days}d, n={shifts.current_sample_size})</strong> vs. <strong>Baseline Cohort ({shifts.baseline_window_days}d, n={shifts.baseline_sample_size})</strong>
            </div>
            {shifts.small_cell_suppression_applied && (
              <span style={{ fontSize: "0.8rem", color: "#a78bfa", background: "rgba(124,58,237,0.1)", padding: "4px 8px", borderRadius: "4px" }}>
                ℹ️ Small cohort suppression active
              </span>
            )}
          </div>

          {/* Quality Metrics Shift Table */}
          <div className="card" style={{ padding: "20px" }}>
            <h3 style={{ fontSize: "1.1rem", margin: "0 0 16px 0", color: "var(--rs-text)" }}>
              Input-Quality Assessment (IQA) Shift Analysis
            </h3>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.88rem" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--rs-border)", textAlign: "left", color: "var(--rs-text-muted)" }}>
                  <th style={{ paddingBottom: "8px" }}>Image Quality Metric</th>
                  <th style={{ paddingBottom: "8px" }}>Baseline Mean (± std)</th>
                  <th style={{ paddingBottom: "8px" }}>Current Mean (± std)</th>
                  <th style={{ paddingBottom: "8px" }}>Delta</th>
                  <th style={{ paddingBottom: "8px" }}>Shift Status</th>
                </tr>
              </thead>
              <tbody>
                {shifts.quality_shift_metrics.map((m, idx) => (
                  <tr key={idx} style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                    <td style={{ padding: "10px 0", fontWeight: 600 }}>{m.metric_name}</td>
                    <td style={{ padding: "10px 0", color: "var(--rs-text-secondary)" }}>
                      {m.baseline_mean !== null ? `${m.baseline_mean} (±${m.baseline_std || 0})` : "N/A"}
                    </td>
                    <td style={{ padding: "10px 0", color: "var(--rs-text-secondary)" }}>
                      {m.current_mean !== null ? `${m.current_mean} (±${m.current_std || 0})` : "N/A"}
                    </td>
                    <td style={{ padding: "10px 0", fontWeight: 600, color: (m.delta_mean || 0) < 0 ? "#ef4444" : "#10b981" }}>
                      {m.delta_mean !== null ? (m.delta_mean > 0 ? `+${m.delta_mean}` : `${m.delta_mean}`) : "N/A"}
                    </td>
                    <td style={{ padding: "10px 0" }}>
                      <span
                        style={{
                          fontSize: "0.75rem",
                          padding: "3px 8px",
                          borderRadius: "12px",
                          background: m.shift_flag ? "rgba(239, 68, 68, 0.15)" : "rgba(16, 185, 129, 0.15)",
                          color: m.shift_flag ? "#ef4444" : "#10b981",
                        }}
                      >
                        {m.shift_flag ? "Shift Detected (>1.5σ)" : "Stable"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Prediction DR Grade Shift Comparison */}
          <div className="card" style={{ padding: "20px" }}>
            <h3 style={{ fontSize: "1.1rem", margin: "0 0 16px 0", color: "var(--rs-text)" }}>
              Predicted DR Severity Distribution Shift
            </h3>
            <p style={{ fontSize: "0.85rem", color: "var(--rs-text-muted)", margin: "0 0 16px 0" }}>
              Monitors shifts in candidate AI output classifications. Changes reflect clinical population or hardware changes and do NOT prove clinical drift.
            </p>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "12px" }}>
              {["Grade 0 (No DR)", "Grade 1 (Mild)", "Grade 2 (Moderate)", "Grade 3 (Severe)", "Grade 4 (PDR)"].map((gradeName) => {
                const bPct = shifts.prediction_dr_grade_shift.baseline?.[gradeName] || 0;
                const cPct = shifts.prediction_dr_grade_shift.current?.[gradeName] || 0;
                const delta = cPct - bPct;
                return (
                  <div
                    key={gradeName}
                    style={{
                      padding: "14px",
                      background: "var(--rs-bg-secondary)",
                      borderRadius: "8px",
                      border: "1px solid var(--rs-border)",
                    }}
                  >
                    <div style={{ fontSize: "0.82rem", color: "var(--rs-text-muted)", marginBottom: "4px" }}>{gradeName}</div>
                    <div style={{ fontSize: "1.3rem", fontWeight: 700, color: "var(--rs-text)" }}>
                      {cPct}% <span style={{ fontSize: "0.8rem", color: "var(--rs-text-muted)" }}>now</span>
                    </div>
                    <div style={{ fontSize: "0.78rem", color: delta > 0 ? "#f59e0b" : delta < 0 ? "#38bdf8" : "var(--rs-text-muted)", marginTop: "4px" }}>
                      Baseline: {bPct}% ({delta >= 0 ? `+${delta.toFixed(1)}%` : `${delta.toFixed(1)}%`})
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* =================================================================== */}
      {/* TAB 3: CLINICAL INTEROPERABILITY (ABDM & FHIR R4) */}
      {/* =================================================================== */}
      {activeTab === "interop" && interop && (
        <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
          {/* Safeguard Banner */}
          <div
            style={{
              padding: "16px 20px",
              background: "rgba(56, 189, 248, 0.08)",
              border: "1px solid rgba(56, 189, 248, 0.3)",
              borderRadius: "10px",
              display: "flex",
              gap: "14px",
              alignItems: "flex-start",
            }}
          >
            <span style={{ fontSize: "1.5rem" }}>🇮🇳</span>
            <div>
              <strong style={{ color: "#38bdf8", fontSize: "0.95rem" }}>
                ABDM & HL7 FHIR R4 INTEROPERABILITY ADAPTER
              </strong>
              <p style={{ margin: "4px 0 0 0", color: "var(--rs-text-secondary)", fontSize: "0.88rem", lineHeight: 1.5 }}>
                {interop.safeguards}
              </p>
            </div>
          </div>

          {/* Status & Readiness Card */}
          <div className="card" style={{ padding: "20px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
              <h3 style={{ fontSize: "1.1rem", margin: 0, color: "var(--rs-text)" }}>
                Integration Readiness & Security Guardrails
              </h3>
              <button
                onClick={handleTestExchange}
                className="btn-secondary"
                disabled={testLoading}
                style={{ fontSize: "0.85rem", padding: "6px 12px" }}
              >
                {testLoading ? "Testing..." : "Verify Live Exchange Readiness"}
              </button>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "14px" }}>
              <div style={{ padding: "12px", background: "var(--rs-bg-secondary)", borderRadius: "6px" }}>
                <div style={{ fontSize: "0.78rem", color: "var(--rs-text-muted)" }}>FHIR Specification</div>
                <div style={{ fontSize: "1.1rem", fontWeight: 700, marginTop: "2px" }}>Release 4 (v{interop.fhir_version})</div>
              </div>

              <div style={{ padding: "12px", background: "var(--rs-bg-secondary)", borderRadius: "6px" }}>
                <div style={{ fontSize: "0.78rem", color: "var(--rs-text-muted)" }}>Live ABDM Gateway</div>
                <div style={{ fontSize: "1.1rem", fontWeight: 700, marginTop: "2px", color: interop.abdm_exchange_enabled ? "#10b981" : "#f59e0b" }}>
                  {interop.abdm_exchange_enabled ? "Enabled" : "Disabled (Safe Default)"}
                </div>
              </div>

              <div style={{ padding: "12px", background: "var(--rs-bg-secondary)", borderRadius: "6px" }}>
                <div style={{ fontSize: "0.78rem", color: "var(--rs-text-muted)" }}>National ID / ABHA Linking</div>
                <div style={{ fontSize: "1.1rem", fontWeight: 700, marginTop: "2px", color: "#38bdf8" }}>
                  Optional (Not Required)
                </div>
              </div>

              <div style={{ padding: "12px", background: "var(--rs-bg-secondary)", borderRadius: "6px" }}>
                <div style={{ fontSize: "0.78rem", color: "var(--rs-text-muted)" }}>Assigned HIP ID</div>
                <div style={{ fontSize: "1.1rem", fontWeight: 700, marginTop: "2px" }}>{interop.hip_id}</div>
              </div>
            </div>

            {exchangeTestResult && (
              <div
                style={{
                  marginTop: "16px",
                  padding: "14px",
                  borderRadius: "8px",
                  background: exchangeTestResult.allowed ? "rgba(16,185,129,0.1)" : "rgba(245,158,11,0.1)",
                  border: `1px solid ${exchangeTestResult.allowed ? "#10b981" : "#f59e0b"}`,
                  fontSize: "0.88rem",
                }}
              >
                <strong>Checklist Diagnostic:</strong> {exchangeTestResult.reason}
                <div style={{ marginTop: "6px", color: "var(--rs-text-secondary)", fontSize: "0.82rem" }}>
                  {exchangeTestResult.guidance}
                </div>
              </div>
            )}
          </div>

          {/* Interactive FHIR Bundle Exporter */}
          <div className="card" style={{ padding: "20px" }}>
            <h3 style={{ fontSize: "1.1rem", margin: "0 0 16px 0", color: "var(--rs-text)" }}>
              Export Clinical Encounter to NRCeS Document Bundle
            </h3>

            <div style={{ display: "flex", gap: "12px", alignItems: "center", marginBottom: "16px", flexWrap: "wrap" }}>
              <select
                value={selectedScreeningId}
                onChange={(e) => setSelectedScreeningId(e.target.value)}
                style={{
                  padding: "8px 12px",
                  background: "var(--rs-bg-secondary)",
                  color: "var(--rs-text)",
                  border: "1px solid var(--rs-border)",
                  borderRadius: "6px",
                  minWidth: "320px",
                }}
              >
                {recentScreenings.map((sc) => (
                  <option key={sc.id} value={sc.id}>
                    Encounter {sc.id.slice(0, 8)} — {sc.eye} eye ({sc.status})
                  </option>
                ))}
              </select>

              <button
                onClick={handleExportFHIR}
                className="btn-primary"
                disabled={exportLoading || !selectedScreeningId}
                style={{ padding: "8px 18px" }}
              >
                {exportLoading ? "Generating..." : "Generate FHIR R4 Document Bundle"}
              </button>
            </div>

            {exportError && (
              <div style={{ padding: "10px 14px", background: "rgba(239,68,68,0.1)", color: "#ef4444", borderRadius: "6px", marginBottom: "16px", fontSize: "0.88rem" }}>
                {exportError}
              </div>
            )}

            {exportedBundle && (
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
                  <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
                    <span
                      style={{
                        padding: "3px 10px",
                        borderRadius: "12px",
                        fontSize: "0.78rem",
                        background: exportedBundle.has_clinician_approval ? "rgba(16,185,129,0.15)" : "rgba(245,158,11,0.15)",
                        color: exportedBundle.has_clinician_approval ? "#10b981" : "#f59e0b",
                        fontWeight: 600,
                      }}
                    >
                      {exportedBundle.composition_status.toUpperCase()} ({exportedBundle.is_provisional ? "AI Provisional" : "Clinician Approved"})
                    </span>
                    <span style={{ fontSize: "0.82rem", color: "var(--rs-text-muted)" }}>
                      SHA-256: <code>{exportedBundle.integrity_sha256.slice(0, 16)}...</code>
                    </span>
                  </div>

                  <button
                    onClick={() => downloadJSON(exportedBundle.bundle_json, `retinashield-fhir-${exportedBundle.screening_id.slice(0, 8)}.json`)}
                    className="btn-secondary"
                    style={{ fontSize: "0.82rem", padding: "4px 12px" }}
                  >
                    📥 Download Bundle (.json)
                  </button>
                </div>

                <pre
                  style={{
                    background: "var(--rs-bg-secondary)",
                    padding: "16px",
                    borderRadius: "8px",
                    maxHeight: "350px",
                    overflowY: "auto",
                    fontSize: "0.82rem",
                    color: "var(--rs-text-secondary)",
                    border: "1px solid var(--rs-border)",
                  }}
                >
                  {JSON.stringify(exportedBundle.bundle_json, null, 2)}
                </pre>
              </div>
            )}
          </div>

          {/* Supported Profiles & Milestones */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(400px, 1fr))", gap: "20px" }}>
            {/* NRCeS Profiles */}
            <div className="card" style={{ padding: "20px" }}>
              <h3 style={{ fontSize: "1.1rem", margin: "0 0 14px 0", color: "var(--rs-text)" }}>
                Supported NRCeS FHIR R4 Profiles
              </h3>
              <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                {interop.supported_profiles.map((p, idx) => (
                  <div key={idx} style={{ padding: "10px", background: "var(--rs-bg-secondary)", borderRadius: "6px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <strong style={{ fontSize: "0.88rem", color: "#38bdf8" }}>{p.profile_name}</strong>
                      <span style={{ fontSize: "0.72rem", padding: "2px 6px", background: "rgba(16,185,129,0.15)", color: "#10b981", borderRadius: "10px" }}>
                        Active Export
                      </span>
                    </div>
                    <p style={{ margin: "4px 0 0 0", fontSize: "0.78rem", color: "var(--rs-text-muted)" }}>
                      {p.description}
                    </p>
                  </div>
                ))}
              </div>
            </div>

            {/* Remaining Requirements */}
            <div className="card" style={{ padding: "20px" }}>
              <h3 style={{ fontSize: "1.1rem", margin: "0 0 14px 0", color: "var(--rs-text)" }}>
                Remaining ABDM Integration Milestones
              </h3>
              <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                {interop.remaining_integration_requirements.map((req, idx) => (
                  <div key={idx} style={{ padding: "10px", background: "var(--rs-bg-secondary)", borderRadius: "6px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <span style={{ fontSize: "0.82rem", fontWeight: 700, color: "#f59e0b" }}>
                        [{req.milestone}] {req.requirement_name}
                      </span>
                      <span style={{ fontSize: "0.72rem", color: "var(--rs-text-muted)" }}>
                        {req.status.replace(/_/g, " ")}
                      </span>
                    </div>
                    <p style={{ margin: "4px 0 0 0", fontSize: "0.78rem", color: "var(--rs-text-muted)" }}>
                      {req.details}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
