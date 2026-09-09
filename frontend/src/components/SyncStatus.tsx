"use client";

import { useEffect, useState } from "react";

interface SyncStatusData {
  facility_id: string;
  server_reachable: boolean;
  queue_stats: {
    pending: number;
    processing: number;
    completed: number;
    synced: number;
    total: number;
  };
}

/**
 * SyncStatus — Displays the facility sync status panel.
 * Shows connectivity, queue stats, and pending sync count.
 */
export function SyncStatus() {
  const [connected, setConnected] = useState<boolean | null>(null);

  useEffect(() => {
    const checkConnection = async () => {
      try {
        const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
        const res = await fetch(`${apiBase}/health`, { method: "GET" });
        setConnected(res.ok);
      } catch {
        setConnected(false);
      }
    };

    checkConnection();
    const interval = setInterval(checkConnection, 30000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="glass-card">
      <h3 style={{ fontSize: "1rem", fontWeight: 700, marginBottom: "12px" }}>
        Connectivity
      </h3>
      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
        <span
          style={{
            width: "10px",
            height: "10px",
            borderRadius: "50%",
            backgroundColor:
              connected === null
                ? "var(--rs-text-muted)"
                : connected
                ? "var(--rs-success)"
                : "var(--rs-danger)",
            display: "inline-block",
            boxShadow: connected
              ? "0 0 8px rgba(34, 197, 94, 0.5)"
              : "none",
          }}
        />
        <span style={{ fontSize: "0.85rem", color: "var(--rs-text-muted)" }}>
          {connected === null
            ? "Checking..."
            : connected
            ? "Server connected"
            : "Server offline — operating in local mode"}
        </span>
      </div>
    </div>
  );
}
