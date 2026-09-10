import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "RetinaShield — Diabetic Retinopathy Screening",
  description:
    "Research prototype for explainable diabetic retinopathy screening in rural Indian primary healthcare centres. All outputs are research screening results — NOT autonomous clinical diagnoses.",
  keywords: [
    "diabetic retinopathy",
    "retinal screening",
    "fundus imaging",
    "deep learning",
    "explainable AI",
    "rural healthcare",
    "India",
  ],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        {/* Persistent Research Disclaimer */}
        <div className="research-disclaimer" style={{ margin: "12px 16px 0", zIndex: 100 }}>
          <span style={{ fontSize: "1.1rem" }}>⚠️</span>
          <span>
            <strong>RESEARCH SCREENING PROTOTYPE</strong> — All outputs are
            research results, not clinical diagnoses. Must be reviewed by a
            qualified ophthalmologist.
          </span>
        </div>

        {/* Navigation */}
        <nav
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "16px 24px",
            borderBottom: "1px solid var(--rs-border)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <span style={{ fontSize: "1.5rem" }}>🛡️</span>
            <span
              style={{
                fontSize: "1.2rem",
                fontWeight: 700,
                background: "linear-gradient(135deg, #14b8a6, #7c3aed)",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
              }}
            >
              RetinaShield
            </span>
          </div>
          <div style={{ display: "flex", gap: "4px" }}>
            <a href="/" className="nav-link">
              Dashboard
            </a>
            <a href="/patients" className="nav-link">
              Patients
            </a>
            <a href="/screening/new" className="nav-link">
              Screening
            </a>
            <a href="/review" className="nav-link">
              Review Queue
            </a>
            <a href="/reports" className="nav-link">
              Reports
            </a>
            <a href="/sync" className="nav-link">
              Sync
            </a>
            <a href="/monitoring" className="nav-link">
              Monitoring
            </a>
            <a href="/settings" className="nav-link">
              Settings
            </a>
            <a href="/login" className="btn-secondary" style={{ padding: '6px 12px', marginLeft: '12px', fontSize: '0.9rem' }}>
              Logout
            </a>
          </div>
        </nav>

        {/* Main Content */}
        <main style={{ padding: "24px", maxWidth: "1400px", margin: "0 auto" }}>
          {children}
        </main>
      </body>
    </html>
  );
}
