"use client";

export function ScoreBadge({ score }: { score: number }) {
  const bg =
    score >= 80 ? "#1e3a2f"
    : score >= 65 ? "#1a3025"
    : score >= 50 ? "#2d2a1e"
    : "#2d1e1e";
  const color =
    score >= 80 ? "#3fb950"
    : score >= 65 ? "#2ea043"
    : score >= 50 ? "#d29922"
    : "#f85149";

  return (
    <span style={{
      display: "inline-block",
      padding: "2px 8px",
      borderRadius: 4,
      background: bg,
      color,
      fontSize: 12,
      fontWeight: 700,
      minWidth: 44,
      textAlign: "center",
    }}>
      {score.toFixed(1)}
    </span>
  );
}

export function RecoBadge({ reco }: { reco: string }) {
  const color =
    reco === "Strong Value" ? "#3fb950"
    : reco === "Good Value"  ? "#2ea043"
    : reco === "Marginal Value" ? "#d29922"
    : "var(--red)";
  return (
    <span style={{ fontSize: 11, color }}>{reco}</span>
  );
}

export function OutcomeBadge({ outcome }: { outcome: string | null }) {
  if (!outcome) return <span style={{ color: "var(--muted)", fontSize: 12 }}>Pending</span>;
  const colors: Record<string, string> = {
    WIN:  "var(--green)",
    LOSS: "var(--red)",
    VOID: "var(--yellow)",
  };
  return (
    <span style={{
      fontSize: 12,
      fontWeight: 700,
      color: colors[outcome] ?? "var(--muted)",
      padding: "2px 8px",
      borderRadius: 4,
      background: outcome === "WIN" ? "#1e3a2f" : outcome === "LOSS" ? "#2d1e1e" : "#2d2a1e",
    }}>
      {outcome}
    </span>
  );
}

export function LegResultBadge({ result }: { result: "HIT" | "MISS" | null }) {
  if (!result) return <span style={{ color: "var(--muted)", fontSize: 11 }}>·</span>;
  return (
    <span style={{
      fontSize: 11,
      color: result === "HIT" ? "var(--green)" : "var(--red)",
      fontWeight: 600,
    }}>
      {result === "HIT" ? "✓" : "✗"}
    </span>
  );
}
