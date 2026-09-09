export default function ScreeningPage() {
  return (
    <div>
      <h1
        style={{
          fontSize: "2rem",
          fontWeight: 800,
          marginBottom: "8px",
          background: "linear-gradient(135deg, #f1f5f9, #14b8a6)",
          WebkitBackgroundClip: "text",
          WebkitTextFillColor: "transparent",
        }}
      >
        DR Screening
      </h1>
      <p style={{ color: "var(--rs-text-muted)", marginBottom: "24px" }}>
        Upload fundus images and run the analysis pipeline.
      </p>

      <div className="glass-card" style={{ textAlign: "center", padding: "60px" }}>
        <p style={{ fontSize: "2rem", marginBottom: "8px" }}>📷</p>
        <p style={{ fontWeight: 600, color: "var(--rs-text)" }}>
          Screening Workflow
        </p>
        <p style={{ fontSize: "0.85rem", color: "var(--rs-text-muted)", marginTop: "4px" }}>
          Full screening workflow (image upload → pipeline → results) will be
          implemented in Phase 5. Backend API is ready at{" "}
          <code>/api/screenings</code> and <code>/api/analysis</code>.
        </p>
      </div>
    </div>
  );
}
