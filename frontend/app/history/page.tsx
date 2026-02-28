"use client";

import { useEffect, useRef, useState } from "react";
import { api, ResultsStatus, SavedSlip } from "@/lib/api";
import { OutcomeBadge, LegResultBadge, ScoreBadge } from "@/components/Badge";
import { PlayerHeadshot } from "@/components/PlayerHeadshot";

/** Return yesterday's date as "YYYY-MM-DD" in local time. */
function yesterday(): string {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return d.toISOString().slice(0, 10);
}

function formatDate(s: string) {
  return s ? s.slice(0, 16).replace("T", " ") : "—";
}

export default function HistoryPage() {
  const [slips, setSlips]       = useState<SavedSlip[]>([]);
  const [loading, setLoading]   = useState(true);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [pending, setPending]   = useState<Record<number, boolean>>({});

  // Auto-check results state
  const [checkDate, setCheckDate]         = useState<string>(yesterday);
  const [checkStatus, setCheckStatus]     = useState<ResultsStatus | null>(null);
  const [checking, setChecking]           = useState(false);
  const checkPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = () => {
    setLoading(true);
    api.history(50).then(setSlips).catch(() => {}).finally(() => setLoading(false));
  };

  useEffect(load, []);

  async function autoCheck() {
    setChecking(true);
    setCheckStatus(null);
    try {
      await api.results.check(checkDate);
      // Immediately fetch status, then poll
      const initial = await api.results.status();
      setCheckStatus(initial);
      if (initial.status === "running") {
        checkPollRef.current = setInterval(async () => {
          try {
            const s = await api.results.status();
            setCheckStatus(s);
            if (s.status !== "running") {
              clearInterval(checkPollRef.current!);
              setChecking(false);
              if (s.status === "done") load();
            }
          } catch { /* ignore */ }
        }, 2000);
      } else {
        setChecking(false);
        if (initial.status === "done") load();
      }
    } catch (e) {
      console.error(e);
      setChecking(false);
    }
  }

  // Clean up poll on unmount
  useEffect(() => () => { if (checkPollRef.current) clearInterval(checkPollRef.current); }, []);

  async function markOutcome(
    slip: SavedSlip,
    outcome: "WIN" | "LOSS" | "VOID",
    stake?: number,
    legResults?: Record<string, "HIT" | "MISS">
  ) {
    setPending(p => ({ ...p, [slip.id]: true }));
    try {
      await api.recordOutcome(slip.id, { outcome, stake, leg_results: legResults });
      load();
    } finally { setPending(p => ({ ...p, [slip.id]: false })); }
  }

  const btn = (color?: string): React.CSSProperties => ({
    padding: "4px 12px", borderRadius: 5, border: `1px solid ${color ?? "var(--border)"}`,
    background: "var(--surface2)", color: color ?? "var(--text)", cursor: "pointer", fontSize: 12,
  });

  const S: React.CSSProperties = { background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 6, padding: "6px 10px", color: "var(--text)", fontSize: 13, outline: "none" };
  const btnStyle = (active?: boolean): React.CSSProperties => ({
    padding: "6px 14px", borderRadius: 6, border: "1px solid var(--border)",
    background: active ? "var(--accent)" : "var(--surface2)",
    color: active ? "#0d1117" : "var(--text)",
    cursor: "pointer", fontSize: 13, fontWeight: active ? 600 : 400,
  });

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ margin: "0 0 4px", fontSize: 20, fontWeight: 700 }}>History</h1>
        <p style={{ margin: 0, color: "var(--muted)", fontSize: 13 }}>Saved slips — mark outcomes manually or auto-check from box scores.</p>
      </div>

      {/* Auto-Check Results control */}
      <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "14px 16px", marginBottom: 20, display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <div style={{ fontSize: 13, fontWeight: 600 }}>Auto-Check Results</div>
        <input
          type="date"
          value={checkDate}
          onChange={e => setCheckDate(e.target.value)}
          style={{ ...S, width: 140 }}
        />
        <button
          style={{ ...btnStyle(true), opacity: checking ? 0.6 : 1 }}
          onClick={autoCheck}
          disabled={checking}
        >
          {checking ? "Checking…" : "Check Results"}
        </button>

        {checkStatus && (
          <div style={{ display: "flex", gap: 12, alignItems: "center", fontSize: 12 }}>
            {checkStatus.status === "running" && (
              <span style={{ color: "var(--accent)" }}>Fetching box scores…</span>
            )}
            {checkStatus.status === "done" && (
              <>
                <span style={{ color: "var(--green)", fontWeight: 600 }}>
                  ✓ {checkStatus.hit} HIT / {checkStatus.miss} MISS
                  {checkStatus.no_data > 0 && ` · ${checkStatus.no_data} no data`}
                </span>
                {checkStatus.slips_resolved > 0 && (
                  <span style={{ color: "var(--accent)" }}>
                    {checkStatus.slips_resolved} slip{checkStatus.slips_resolved !== 1 ? "s" : ""} auto-resolved
                  </span>
                )}
              </>
            )}
            {checkStatus.status === "error" && (
              <span style={{ color: "var(--red)" }}>Error: {checkStatus.error}</span>
            )}
          </div>
        )}

        <div style={{ marginLeft: "auto", fontSize: 11, color: "var(--muted)" }}>
          Grades all saved legs for that game date from NBA box scores
        </div>
      </div>

      {loading ? (
        <div style={{ color: "var(--muted)", padding: "60px 0", textAlign: "center" }}>Loading…</div>
      ) : slips.length === 0 ? (
        <div style={{ color: "var(--muted)", padding: "60px 0", textAlign: "center" }}>
          No saved slips yet. Go to <strong style={{ color: "var(--text)" }}>Slips</strong> and save one.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {slips.map(slip => (
            <div key={slip.id} style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
              {/* Header */}
              <div style={{ padding: "12px 16px", display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8, borderBottom: "1px solid var(--border)" }}>
                <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
                  <span style={{ fontSize: 12, color: "var(--muted)" }}>#{slip.id}</span>
                  <span style={{ fontSize: 12, color: "var(--muted)" }}>{formatDate(slip.saved_at)}</span>
                  <span style={{ fontSize: 14, fontWeight: 700, color: "var(--accent)" }}>{slip.combined_odds?.toFixed(2) ?? "—"}</span>
                  <span style={{ fontSize: 12, color: "var(--muted)" }}>Target: {slip.target_odds_str}</span>
                  <span style={{ fontSize: 12, color: "var(--muted)" }}>Score: {slip.avg_value_score?.toFixed(1) ?? "—"}</span>
                  {slip.bookmaker_filter && <span style={{ fontSize: 11, color: "var(--muted)" }}>📚 {slip.bookmaker_filter}</span>}
                </div>

                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <OutcomeBadge outcome={slip.outcome} />
                  <button style={btn()} onClick={() => setExpanded(expanded === slip.id ? null : slip.id)}>
                    {expanded === slip.id ? "▲ Hide" : "▼ Details"}
                  </button>
                </div>
              </div>

              {/* Legs summary */}
              <div style={{ padding: "10px 16px" }}>
                {slip.legs.map(leg => (
                  <div key={leg.id} style={{ display: "flex", alignItems: "center", gap: 14, padding: "4px 0" }}>
                    <LegResultBadge result={leg.leg_result} />
                    <ScoreBadge score={leg.value_score ?? 0} />
                    <PlayerHeadshot playerId={leg.nba_player_id} size={36} />
                    <span style={{ fontWeight: 600, fontSize: 13 }}>{leg.player_name}</span>
                    <span style={{ color: "var(--muted)", fontSize: 13 }}>{(leg.side ?? "over").toUpperCase()} {leg.line} {leg.market_label}</span>
                    <span style={{ color: "var(--accent)", fontSize: 12, marginLeft: "auto" }}>{leg.over_odds?.toFixed(2) ?? "—"}</span>
                    <span style={{ color: "var(--muted)", fontSize: 11 }}>{leg.is_paddy_power ? "🍀 PP" : leg.bookmaker}</span>
                  </div>
                ))}
              </div>

              {/* Mark outcome — shown when expanded */}
              {expanded === slip.id && (
                <div style={{ borderTop: "1px solid var(--border)", padding: "14px 16px", background: "var(--bg)" }}>
                  {/* Outcome buttons */}
                  {!slip.outcome && (
                    <div style={{ marginBottom: 16 }}>
                      <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 8 }}>Mark slip result:</div>
                      <SlipOutcomeForm
                        slip={slip}
                        onSave={(outcome, stake, legResults) => markOutcome(slip, outcome, stake, legResults)}
                        disabled={pending[slip.id]}
                      />
                    </div>
                  )}

                  {slip.outcome && (
                    <div style={{ marginBottom: 12, display: "flex", gap: 16, fontSize: 13 }}>
                      {slip.stake != null && <span>Stake: <strong>{slip.stake}</strong></span>}
                      {slip.profit_loss != null && (
                        <span style={{ color: slip.profit_loss >= 0 ? "var(--green)" : "var(--red)" }}>
                          P&L: <strong>{slip.profit_loss >= 0 ? "+" : ""}{slip.profit_loss.toFixed(2)}</strong>
                        </span>
                      )}
                      {slip.result_at && <span style={{ color: "var(--muted)" }}>Settled: {formatDate(slip.result_at)}</span>}
                    </div>
                  )}

                  {/* Factor scores table */}
                  <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 6 }}>Factor scores at prediction time:</div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px 16px" }}>
                    {slip.legs.map(leg => (
                      <div key={leg.id} style={{ background: "var(--surface)", borderRadius: 6, padding: "8px 12px" }}>
                        <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 6 }}>
                          {leg.player_name} — {leg.market_label}
                        </div>
                        {[
                          ["Consistency", leg.score_consistency],
                          ["vs Opponent", leg.score_vs_opponent],
                          ["Home/Away", leg.score_home_away],
                          ["Injury", leg.score_injury],
                          ["Team Context", leg.score_team_context],
                          ["Season Avg", leg.score_season_avg],
                          ["Blowout Risk", leg.score_blowout_risk],
                          ["Volume & Usage", leg.score_volume_context],
                        ].map(([label, val]) =>
                          val != null ? (
                            <div key={label as string} style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 2 }}>
                              <span style={{ color: "var(--muted)" }}>{label}</span>
                              <span style={{ color: (val as number) >= 65 ? "var(--green)" : (val as number) >= 45 ? "var(--yellow)" : "var(--red)" }}>
                                {(val as number).toFixed(0)}
                              </span>
                            </div>
                          ) : null
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Outcome form ─────────────────────────────────────────────────────────────

function SlipOutcomeForm({
  slip,
  onSave,
  disabled,
}: {
  slip: SavedSlip;
  onSave: (o: "WIN" | "LOSS" | "VOID", stake?: number, legs?: Record<string, "HIT" | "MISS">) => void;
  disabled?: boolean;
}) {
  const [outcome, setOutcome]   = useState<"WIN" | "LOSS" | "VOID" | "">("");
  const [stake, setStake]       = useState("");
  const [legResults, setLegResults] = useState<Record<string, "HIT" | "MISS">>({});

  function toggleLeg(id: number, result: "HIT" | "MISS") {
    setLegResults(r => {
      const next = { ...r };
      if (next[String(id)] === result) delete next[String(id)]; else next[String(id)] = result;
      return next;
    });
  }

  const S: React.CSSProperties = { background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 6, padding: "5px 8px", color: "var(--text)", fontSize: 13, outline: "none" };
  const ob = (o: "WIN" | "LOSS" | "VOID"): React.CSSProperties => {
    const colors = { WIN: "var(--green)", LOSS: "var(--red)", VOID: "var(--yellow)" };
    return { padding: "5px 16px", borderRadius: 5, border: `1px solid ${colors[o]}`, background: outcome === o ? colors[o] : "var(--surface2)", color: outcome === o ? "#0d1117" : colors[o], cursor: "pointer", fontSize: 13, fontWeight: 600 };
  };

  return (
    <div>
      {/* Leg results */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 6 }}>Mark each leg:</div>
        {slip.legs.map(leg => (
          <div key={leg.id} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
            <span style={{ minWidth: 200, fontSize: 12 }}>{leg.player_name} {leg.market_label}</span>
            <button style={{ padding: "3px 10px", borderRadius: 4, border: `1px solid var(--green)`, background: legResults[leg.id] === "HIT" ? "var(--green)" : "var(--surface2)", color: legResults[leg.id] === "HIT" ? "#0d1117" : "var(--green)", cursor: "pointer", fontSize: 11 }}
              onClick={() => toggleLeg(leg.id, "HIT")}>HIT</button>
            <button style={{ padding: "3px 10px", borderRadius: 4, border: "1px solid var(--red)", background: legResults[leg.id] === "MISS" ? "var(--red)" : "var(--surface2)", color: legResults[leg.id] === "MISS" ? "#fff" : "var(--red)", cursor: "pointer", fontSize: 11 }}
              onClick={() => toggleLeg(leg.id, "MISS")}>MISS</button>
          </div>
        ))}
      </div>

      {/* Stake */}
      <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 12 }}>
        <span style={{ fontSize: 12, color: "var(--muted)" }}>Stake (optional):</span>
        <input style={{ ...S, width: 80 }} type="number" placeholder="10" value={stake} onChange={e => setStake(e.target.value)} />
      </div>

      {/* Outcome buttons */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {(["WIN", "LOSS", "VOID"] as const).map(o => (
          <button key={o} style={ob(o)} onClick={() => setOutcome(prev => prev === o ? "" : o)}>{o}</button>
        ))}
        {outcome && (
          <button
            disabled={disabled}
            style={{ padding: "5px 16px", borderRadius: 5, border: "1px solid var(--accent)", background: "var(--accent)", color: "#0d1117", cursor: "pointer", fontSize: 13, fontWeight: 700 }}
            onClick={() => onSave(outcome, stake ? Number(stake) : undefined, Object.keys(legResults).length ? legResults : undefined)}
          >
            Save Result
          </button>
        )}
      </div>
    </div>
  );
}
