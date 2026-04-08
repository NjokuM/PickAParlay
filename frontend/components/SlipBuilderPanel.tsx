"use client";

import { useState } from "react";
import { useSlipBuilder } from "@/lib/slip-builder-context";
import { api } from "@/lib/api";
import { ScoreBadge } from "@/components/Badge";
import { useIsMobile } from "@/hooks/useIsMobile";

function scoreColor(s: number): string {
  if (s >= 80) return "var(--green)";
  if (s >= 65) return "#2ea043";
  if (s >= 50) return "var(--yellow)";
  return "var(--red)";
}

export default function SlipBuilderPanel() {
  const { legs, removeLeg, clearSlip, combinedOdds, avgScore } = useSlipBuilder();
  const [expanded, setExpanded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<number | null>(null);
  const isMobile = useIsMobile();

  if (legs.length === 0) return null;

  async function handleSave() {
    setSaving(true); setSaved(null);
    try {
      const res = await api.saveCustomSlip(legs.map((l) => l.propId));
      setSaved(res.slip_id);
    } catch (e) {
      console.error("Failed to save custom slip:", e);
    } finally { setSaving(false); }
  }

  function handleClear() { clearSlip(); setSaved(null); setExpanded(false); }

  // ── Collapsed pill ──
  if (!expanded) {
    return (
      <button
        onClick={() => setExpanded(true)}
        style={{
          position: "fixed",
          bottom: isMobile ? 68 : 20,
          right: isMobile ? 12 : 20,
          zIndex: 1000,
          background: "var(--accent)", color: "#0d1117",
          border: "none", borderRadius: 24,
          padding: "10px 20px", fontSize: 14, fontWeight: 700,
          cursor: "pointer",
          display: "flex", alignItems: "center", gap: 8,
          boxShadow: "0 4px 20px rgba(0,0,0,0.4)",
        }}
      >
        My Slip
        <span style={{
          background: "#0d1117", color: "var(--accent)",
          borderRadius: 12, padding: "2px 8px", fontSize: 12, fontWeight: 700,
        }}>
          {legs.length}
        </span>
      </button>
    );
  }

  // ── Expanded panel ──
  return (
    <div style={{
      position: "fixed",
      bottom: isMobile ? 56 : 20,
      right: isMobile ? 0 : 20,
      left: isMobile ? 0 : "auto",
      zIndex: 1000,
      width: isMobile ? "100%" : 380,
      maxHeight: isMobile ? "70vh" : "60vh",
      background: "var(--surface)",
      border: "1px solid var(--border)",
      borderRadius: isMobile ? "12px 12px 0 0" : 12,
      boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
      display: "flex", flexDirection: "column", overflow: "hidden",
    }}>
      {/* Header */}
      <div style={{
        padding: "12px 16px", borderBottom: "1px solid var(--border)",
        display: "flex", alignItems: "center", justifyContent: "space-between",
        background: "var(--surface2)",
      }}>
        <div style={{ fontWeight: 700, fontSize: 14 }}>
          My Slip ({legs.length} leg{legs.length !== 1 ? "s" : ""})
        </div>
        <button onClick={() => setExpanded(false)} style={{
          background: "none", border: "none", color: "var(--muted)",
          cursor: "pointer", fontSize: 18, padding: "0 4px",
        }}>▾</button>
      </div>

      {/* Legs list */}
      <div style={{ flex: 1, overflowY: "auto", padding: "8px 0" }}>
        {legs.map((leg) => (
          <div key={leg.propId} style={{
            display: "flex", alignItems: "center", gap: 10,
            padding: "8px 16px", borderBottom: "1px solid var(--border)",
          }}>
            <ScoreBadge score={leg.valueScore} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 600, fontSize: 13, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                {leg.playerName}
              </div>
              <div style={{ fontSize: 11, color: "var(--muted)" }}>
                <span style={{ color: leg.side === "over" ? "var(--green)" : "var(--red)", fontWeight: 600 }}>
                  {leg.side.toUpperCase()}
                </span>
                {" "}{leg.line} {leg.marketLabel}
              </div>
            </div>
            <div style={{ fontSize: 13, color: "var(--accent)", fontWeight: 600, whiteSpace: "nowrap" }}>
              {leg.decimalOdds.toFixed(2)}
            </div>
            <button onClick={() => removeLeg(leg.propId)} style={{
              background: "none", border: "none", color: "var(--red)",
              cursor: "pointer", fontSize: 16, padding: "0 4px", lineHeight: 1,
            }} title="Remove">✕</button>
          </div>
        ))}
      </div>

      {/* Stats bar */}
      <div style={{
        padding: "10px 16px", borderTop: "1px solid var(--border)",
        display: "flex", gap: isMobile ? 12 : 20, alignItems: "center",
        background: "var(--surface2)", flexWrap: "wrap",
      }}>
        <div>
          <div style={{ fontSize: 10, color: "var(--muted)", textTransform: "uppercase" }}>Combined Odds</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: "var(--accent)" }}>{combinedOdds.toFixed(2)}</div>
        </div>
        <div>
          <div style={{ fontSize: 10, color: "var(--muted)", textTransform: "uppercase" }}>Avg Score</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: scoreColor(avgScore) }}>{avgScore.toFixed(1)}</div>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <button onClick={handleClear} style={{
            background: "transparent", border: "1px solid var(--border)", borderRadius: 6,
            color: "var(--muted)", padding: "6px 12px", fontSize: 12, cursor: "pointer",
          }}>Clear</button>
          <button onClick={handleSave} disabled={saving || legs.length === 0} style={{
            background: "var(--accent)", border: "none", borderRadius: 6,
            color: "#0d1117", padding: "6px 16px", fontSize: 12, fontWeight: 700,
            cursor: saving ? "wait" : "pointer", opacity: saving ? 0.6 : 1,
          }}>{saving ? "Saving…" : "Save Slip"}</button>
        </div>
      </div>

      {saved && (
        <div style={{
          padding: "8px 16px", background: "#1a2e1a",
          borderTop: "1px solid var(--green)", color: "var(--green)",
          fontSize: 12, textAlign: "center",
        }}>
          Saved as slip #{saved} — view in History
        </div>
      )}
    </div>
  );
}
