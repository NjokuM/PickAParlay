"use client";

import { Factor } from "@/lib/api";

const COLORS: Record<string, string> = {
  Consistency:       "#58a6ff",
  "vs Opponent":     "#bc8cff",
  "Home/Away":       "#ffa657",
  "Injury Context":  "#3fb950",
  "Team Context":    "#39d353",
  "Season Average":  "#f0883e",
  "Blowout Risk":    "#f85149",
  "Line Value":      "#6e7681",
  "Volume & Usage":  "#56d364",
};

function scoreColor(s: number): string {
  if (s >= 80) return "#3fb950";
  if (s >= 65) return "#2ea043";
  if (s >= 50) return "var(--yellow)";
  return "var(--red)";
}

export function FactorBar({ factor }: { factor: Factor }) {
  const color = COLORS[factor.name] ?? "var(--accent)";
  return (
    <div style={{ marginBottom: 6 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
        <span style={{ fontSize: 12, color: "var(--muted)" }}>
          {factor.name}
          <span style={{ color: "var(--border)", marginLeft: 4 }}>
            {(factor.weight * 100).toFixed(0)}%
          </span>
        </span>
        <span style={{ fontSize: 12, fontWeight: 600, color: scoreColor(factor.score) }}>
          {factor.score.toFixed(0)}
        </span>
      </div>
      <div style={{
        height: 5,
        background: "var(--surface2)",
        borderRadius: 3,
        overflow: "hidden",
      }}>
        <div style={{
          width: `${factor.score}%`,
          height: "100%",
          background: color,
          borderRadius: 3,
          transition: "width 0.4s ease",
        }} />
      </div>
      {factor.evidence && factor.evidence.length > 0 && (
        <ul style={{ margin: "4px 0 0", padding: "0 0 0 12px", listStyle: "disc" }}>
          {factor.evidence.map((e, i) => (
            <li key={i} style={{ fontSize: 11, color: "var(--muted)", marginBottom: 1 }}>{e}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function FactorGrid({ factors }: { factors: Factor[] }) {
  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: "8px 20px",
      padding: "12px 0",
    }}>
      {factors.map((f) => (
        <FactorBar key={f.name} factor={f} />
      ))}
    </div>
  );
}
