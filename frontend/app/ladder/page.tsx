"use client";

import { useEffect, useState, useRef } from "react";
import { api, Slip, LadderStatus } from "@/lib/api";
import { FactorGrid } from "@/components/FactorBar";
import { ScoreBadge } from "@/components/Badge";
import { PlayerHeadshot } from "@/components/PlayerHeadshot";

function bookmakerLabel(b: string) {
  const m: Record<string, string> = { paddypower: "Paddy Power", draftkings: "DraftKings", fanduel: "FanDuel", betmgm: "BetMGM" };
  return m[b] ?? b;
}

const btn = (active?: boolean): React.CSSProperties => ({
  padding: "6px 14px", borderRadius: 6, border: "1px solid var(--border)",
  background: active ? "var(--accent)" : "var(--surface2)",
  color: active ? "#0d1117" : "var(--text)",
  cursor: "pointer", fontSize: 13, fontWeight: active ? 600 : 400,
});

const statusLabel: Record<string, { text: string; color: string }> = {
  idle:     { text: "Not run yet",      color: "var(--muted)"  },
  running:  { text: "Searching…",       color: "var(--accent)" },
  done:     { text: "Done",             color: "var(--green)"  },
  no_games: { text: "No games tonight", color: "var(--muted)"  },
  no_props: { text: "No alternate props found", color: "var(--orange)" },
  error:    { text: "Error",            color: "var(--red)"    },
};

export default function LadderPage() {
  const [status, setStatus]     = useState<LadderStatus | null>(null);
  const [slips, setSlips]       = useState<Slip[]>([]);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [triggering, setTriggering] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Load status on mount
  useEffect(() => {
    api.ladder.status().then(setStatus).catch(() => {});
    api.ladder.results().then(setSlips).catch(() => {});
  }, []);

  // Poll while running
  useEffect(() => {
    if (status?.status === "running") {
      pollRef.current = setInterval(async () => {
        try {
          const s = await api.ladder.status();
          setStatus(s);
          if (s.status !== "running") {
            clearInterval(pollRef.current!);
            if (s.status === "done") {
              const results = await api.ladder.results();
              setSlips(results);
            }
          }
        } catch { /* ignore */ }
      }, 2000);
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [status?.status]);

  async function runLadder() {
    setTriggering(true);
    setSlips([]);
    setExpanded(null);
    try {
      await api.ladder.trigger();
      const s = await api.ladder.status();
      setStatus(s);
    } catch (e) {
      console.error(e);
    } finally {
      setTriggering(false);
    }
  }

  const isRunning = status?.status === "running";
  const sl = status ? statusLabel[status.status] ?? statusLabel.idle : statusLabel.idle;

  // Separate single-leg from multi-leg picks
  const singles = slips.filter(s => s.type === "single");
  const multis  = slips.filter(s => s.type !== "single");

  return (
    <div>
      {/* Header */}
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ margin: "0 0 4px", fontSize: 20, fontWeight: 700 }}>🪜 Ladder Challenge</h1>
        <p style={{ margin: 0, color: "var(--muted)", fontSize: 13 }}>
          Find the highest-confidence bets at near even money (1.95–2.30 decimal).
          Uses alternate prop lines — multiple thresholds per player, priced at different odds.
        </p>
      </div>

      {/* Controls bar */}
      <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "16px", marginBottom: 20, display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
        <button
          style={{ ...btn(true), padding: "8px 20px", opacity: isRunning || triggering ? 0.6 : 1 }}
          onClick={runLadder}
          disabled={isRunning || triggering}
        >
          {isRunning || triggering ? "Searching…" : "Run Ladder"}
        </button>

        {status && (
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 12, color: sl.color, fontWeight: 600 }}>{sl.text}</span>
            {status.status === "running" && (
              <span style={{ fontSize: 12, color: "var(--muted)" }}>{status.props_graded} props graded</span>
            )}
            {status.status === "done" && (
              <span style={{ fontSize: 12, color: "var(--muted)" }}>{status.props_graded} props graded · {slips.length} picks found</span>
            )}
            {status.error && (
              <span style={{ fontSize: 12, color: "var(--red)", maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{status.error}</span>
            )}
          </div>
        )}

        {/* Odds window badge */}
        <div style={{ marginLeft: "auto", padding: "4px 12px", borderRadius: 20, background: "var(--surface2)", border: "1px solid var(--border)", fontSize: 12, color: "var(--accent)", fontWeight: 600 }}>
          Target: 1.95 – 2.30
        </div>
      </div>

      {slips.length === 0 && !isRunning && !triggering && (
        <div style={{ color: "var(--muted)", padding: "40px 0", textAlign: "center", fontSize: 14 }}>
          {status?.status === "idle" || !status
            ? 'Click "Run Ladder" to search for near even money picks using alternate lines.'
            : status?.status === "no_games" ? "No NBA games tonight."
            : status?.status === "no_props" ? "No alternate props available for tonight's games."
            : "No ladder picks found."}
        </div>
      )}

      {/* Single-leg picks */}
      {singles.length > 0 && (
        <div style={{ marginBottom: 24 }}>
          <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
            Single Picks
            <span style={{ fontSize: 11, fontWeight: 400, color: "var(--muted)" }}>— one leg at even money</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {singles.map((slip, idx) => (
              <SlipCard key={`s-${idx}`} slip={slip} idx={idx} expanded={expanded} setExpanded={setExpanded} prefix="s" />
            ))}
          </div>
        </div>
      )}

      {/* Multi-leg parlays */}
      {multis.length > 0 && (
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
            Parlays at ~2.0
            <span style={{ fontSize: 11, fontWeight: 400, color: "var(--muted)" }}>— 2–4 legs combining to even money</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {multis.map((slip, idx) => (
              <SlipCard key={`m-${idx}`} slip={slip} idx={idx} expanded={expanded} setExpanded={setExpanded} prefix="m" />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Shared slip card ─────────────────────────────────────────────────────────

function SlipCard({
  slip, idx, expanded, setExpanded, prefix,
}: {
  slip: Slip;
  idx: number;
  expanded: number | null;
  setExpanded: (v: number | null) => void;
  prefix: string;
}) {
  const cardKey = prefix === "s" ? -(idx + 1) : idx;   // unique key for expand state
  const isExpanded = expanded === cardKey;

  const btn = (active?: boolean): React.CSSProperties => ({
    padding: "6px 14px", borderRadius: 6, border: "1px solid var(--border)",
    background: active ? "var(--accent)" : "var(--surface2)",
    color: active ? "#0d1117" : "var(--text)",
    cursor: "pointer", fontSize: 13,
  });

  return (
    <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
      {/* Header */}
      <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
          <div>
            <span style={{ fontSize: 11, color: "var(--muted)" }}>Odds</span>
            <div style={{ fontSize: 20, fontWeight: 700, color: "var(--accent)" }}>{slip.combined_odds.toFixed(2)}</div>
          </div>
          <div>
            <span style={{ fontSize: 11, color: "var(--muted)" }}>Avg Score</span>
            <div style={{ fontSize: 18, fontWeight: 700 }}>{slip.avg_value_score.toFixed(1)}</div>
          </div>
          <div>
            <span style={{ fontSize: 11, color: "var(--muted)" }}>Legs</span>
            <div style={{ fontSize: 18, fontWeight: 700 }}>{slip.legs.length}</div>
          </div>
          {slip.has_correlated_legs && (
            <span style={{ fontSize: 11, color: "var(--orange)", background: "#2d2a1e", padding: "2px 8px", borderRadius: 4 }}>⚠ correlated</span>
          )}
        </div>
        <button style={btn(isExpanded)} onClick={() => setExpanded(isExpanded ? null : cardKey)}>
          {isExpanded ? "Hide detail" : "View detail"}
        </button>
      </div>

      {/* Legs summary */}
      <div style={{ padding: "12px 16px" }}>
        {slip.legs.map((leg, li) => (
          <div key={li} style={{ display: "flex", alignItems: "center", gap: 14, padding: "6px 0", borderBottom: li < slip.legs.length - 1 ? "1px solid var(--border)" : "none" }}>
            <ScoreBadge score={leg.value_score} />
            <PlayerHeadshot playerId={leg.player_id} size={40} />
            <div style={{ flex: 1 }}>
              <span style={{ fontWeight: 600 }}>{leg.player_name}</span>
              <span style={{ color: "var(--muted)", marginLeft: 8, fontSize: 13 }}>
                {(leg.side ?? "over").toUpperCase()} {leg.line} {leg.market_label}
              </span>
            </div>
            <div style={{ color: "var(--accent)", fontSize: 13 }}>{leg.over_odds.toFixed(2)}</div>
            <div style={{ fontSize: 12, color: "var(--muted)", minWidth: 90, textAlign: "right" }}>
              {leg.is_paddy_power ? "🍀 PP" : bookmakerLabel(leg.bookmaker)}
            </div>
            <div style={{ fontSize: 11, color: "var(--muted)", minWidth: 110, textAlign: "right" }}>{leg.game}</div>
          </div>
        ))}
      </div>

      {/* Expanded factor detail */}
      {isExpanded && (
        <div style={{ borderTop: "1px solid var(--border)", background: "var(--bg)" }}>
          {slip.legs.map((leg, li) => (
            <div key={li} style={{ padding: "16px 20px", borderBottom: li < slip.legs.length - 1 ? "1px solid var(--border)" : "none" }}>
              <div style={{ fontWeight: 600, marginBottom: 10 }}>
                {leg.player_name} — {(leg.side ?? "over").toUpperCase()} {leg.line} {leg.market_label}
                <span style={{ color: "var(--muted)", fontWeight: 400, marginLeft: 8, fontSize: 12 }}>{leg.game}</span>
              </div>
              <FactorGrid factors={leg.factors} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
