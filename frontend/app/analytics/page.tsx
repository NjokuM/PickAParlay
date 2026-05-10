"use client";

import { useEffect, useState } from "react";
import { api, Analytics } from "@/lib/api";
import { isAdmin } from "@/lib/auth";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, ReferenceLine, CartesianGrid, Legend,
} from "recharts";
import { useIsMobile } from "@/hooks/useIsMobile";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function pct(hits: number, total: number) {
  return total ? Math.round((hits / total) * 100) : 0;
}

function pctColor(p: number) {
  return p >= 60 ? "var(--green)" : p >= 48 ? "var(--accent)" : "var(--red)";
}

const CARD: React.CSSProperties = {
  background: "var(--surface)", border: "1px solid var(--border)",
  borderRadius: 8, padding: 20,
};

const FACTOR_ORDER = [
  "Consistency", "Opponent Defense", "vs Opponent", "Home/Away", "Injury",
  "Season Avg", "Blowout Risk", "Volume & Usage",
];

const THRESHOLD_OPTIONS = [60, 65, 70, 75, 80] as const;

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function AnalyticsPage() {
  const isMobile = useIsMobile();
  const admin = isAdmin();

  const [data, setData]         = useState<Analytics | null>(null);
  const [loading, setLoading]   = useState(true);
  const [activeFactor, setActiveFactor] = useState("Consistency");
  const [analyticsView, setAnalyticsView] = useState<"regular" | "alt">("regular");
  const [minScore, setMinScore] = useState<number>(65);

  useEffect(() => {
    setLoading(true);
    api.analytics(minScore).then(setData).catch(() => {}).finally(() => setLoading(false));
  }, [minScore]);

  if (loading) return <div style={{ color: "var(--muted)", padding: "60px 0", textAlign: "center" }}>Loading…</div>;
  if (!data) return null;

  const section = analyticsView === "regular" ? data.regular : data.alt;
  const { picks, value_calibration, factor_calibration, by_market, by_side, daily_trend, daily_pnl, threshold_table } = section;
  const { slips } = data;
  const noData = picks.total === 0;

  // ── Derived chart data ────────────────────────────────────────────────

  const valCalData = value_calibration.map(r => ({
    bucket: `${r.bucket}–${r.bucket + 4}`,
    bucket_mid: r.bucket + 2.5,
    actual_pct: pct(r.hits, r.total),
    sample: r.total,
    hits: r.hits,
  }));

  const activeFactorData = (factor_calibration[activeFactor] ?? []).map(r => ({
    bucket: `${r.bucket}–${r.bucket + 9}`,
    actual_pct: pct(r.hits, r.total),
    ideal: Math.min(100, r.bucket + 5),
    sample: r.total,
    hits: r.hits,
  }));

  const trendData = daily_trend.map(r => ({
    date: r.game_date.slice(5),   // "MM-DD"
    hit_pct: pct(r.hits, r.total),
    total: r.total,
    hits: r.hits,
  }));

  // Cumulative ROI chart data — running total of flat-stake units
  const cumulativePnlData = daily_pnl.reduce<
    { date: string; cumulative_roi: number; day_roi: number; picks: number }[]
  >((acc, r) => {
    const prev = acc.length > 0 ? acc[acc.length - 1].cumulative_roi : 0;
    acc.push({
      date: r.game_date.slice(5),
      cumulative_roi: Math.round((prev + r.day_roi_units) * 10) / 10,
      day_roi: Math.round(r.day_roi_units * 10) / 10,
      picks: r.picks,
    });
    return acc;
  }, []);

  // ── OVER / UNDER side summaries ────────────────────────────────────
  const overRow  = by_side.find(r => r.side === "over");
  const underRow = by_side.find(r => r.side === "under");
  const impliedPct = picks.implied_prob_pct ?? 52.0; // market breakeven

  // ── Factor summary: overall hit rate per factor's high-score bracket ──
  const factorSummary = FACTOR_ORDER.map(name => {
    const buckets = factor_calibration[name] ?? [];
    const highBuckets = buckets.filter(b => b.bucket >= 60);
    const totalHigh = highBuckets.reduce((s, b) => s + b.total, 0);
    const hitsHigh  = highBuckets.reduce((s, b) => s + b.hits, 0);
    const allTotal  = buckets.reduce((s, b) => s + b.total, 0);
    const allHits   = buckets.reduce((s, b) => s + b.hits, 0);
    return {
      name,
      overall_pct: pct(allHits, allTotal),
      overall_n:   allTotal,
      high_pct:    pct(hitsHigh, totalHigh),
      high_n:      totalHigh,
    };
  });

  // ── Pill style helper ────────────────────────────────────────────────
  const pill = (active: boolean): React.CSSProperties => ({
    padding: "4px 12px", borderRadius: 4, border: "1px solid var(--border)",
    background: active ? "var(--accent)" : "var(--surface2)",
    color: active ? "#0d1117" : "var(--muted)",
    cursor: "pointer", fontSize: 12, fontWeight: active ? 600 : 400,
  });

  return (
    <div>
      {/* ── Header + Controls ── */}
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ margin: "0 0 4px", fontSize: 20, fontWeight: 700 }}>📈 Analytics</h1>
        <p style={{ margin: 0, color: "var(--muted)", fontSize: 13 }}>
          {analyticsView === "regular"
            ? `Performance tracking for recommended picks (${minScore}+ score only).`
            : `Alt-line accuracy from ladder picks (${minScore}+ score only).`}
          {noData && " Run a refresh then check results to see data here."}
        </p>

        {/* Regular / Alt toggle */}
        <div style={{ display: "flex", gap: 6, marginTop: 12, flexWrap: "wrap" }}>
          <button style={pill(analyticsView === "regular")} onClick={() => setAnalyticsView("regular")}>
            Regular Props
          </button>
          <button style={pill(analyticsView === "alt")} onClick={() => setAnalyticsView("alt")}>
            Alt Lines
          </button>
        </div>

        {/* Min score threshold selector — admin only */}
        {admin && (
          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.05em" }}>
              Min Score Threshold
            </div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {THRESHOLD_OPTIONS.map(t => (
                <button key={t} style={pill(minScore === t)} onClick={() => setMinScore(t)}>
                  {t}+
                </button>
              ))}
            </div>
            <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 4 }}>
              Only picks at or above this score count toward analytics. Default 65 = recommendation threshold.
            </div>
          </div>
        )}
      </div>

      {/* ── Hero KPI Row — the 4 numbers that answer "does the model work?" ── */}
      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "repeat(2, 1fr)" : "repeat(4, 1fr)", gap: 12, marginBottom: 24 }}>
        {/* Hit Rate */}
        <div style={CARD}>
          <div style={{ fontSize: 11, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 8 }}>Hit Rate</div>
          <div style={{ fontSize: 28, fontWeight: 700, color: picks.hit_rate >= 0.55 ? "var(--green)" : picks.hit_rate >= 0.50 ? "var(--accent)" : "var(--red)" }}>
            {picks.total > 0 ? `${(picks.hit_rate * 100).toFixed(1)}%` : "—"}
          </div>
          <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 4 }}>
            {picks.hits} hits · {picks.misses} misses · {picks.total} picks
          </div>
        </div>
        {/* Market Implied */}
        <div style={CARD}>
          <div style={{ fontSize: 11, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 8 }}>Market Implied</div>
          <div style={{ fontSize: 28, fontWeight: 700, color: "var(--text)" }}>
            {picks.implied_prob_pct != null ? `${picks.implied_prob_pct.toFixed(1)}%` : "—"}
          </div>
          <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 4 }}>
            {picks.avg_decimal_odds != null ? `avg odds ${picks.avg_decimal_odds.toFixed(2)}` : "breakeven probability"}
          </div>
        </div>
        {/* Edge — THE number */}
        <div style={{ ...CARD, borderColor: picks.edge_pct != null && picks.edge_pct > 0 ? "var(--green)" : picks.edge_pct != null && picks.edge_pct < 0 ? "var(--red)" : "var(--border)" }}>
          <div style={{ fontSize: 11, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 8 }}>Edge vs Market</div>
          <div style={{ fontSize: 28, fontWeight: 700, color: picks.edge_pct != null ? picks.edge_pct > 0 ? "var(--green)" : "var(--red)" : "var(--muted)" }}>
            {picks.edge_pct != null ? `${picks.edge_pct > 0 ? "+" : ""}${picks.edge_pct.toFixed(1)}pp` : "—"}
          </div>
          <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 4 }}>
            hit rate − implied prob
          </div>
        </div>
        {/* ROI */}
        <div style={CARD}>
          <div style={{ fontSize: 11, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 8 }}>ROI (flat stake)</div>
          <div style={{ fontSize: 28, fontWeight: 700, color: picks.roi_pct != null ? picks.roi_pct > 0 ? "var(--green)" : "var(--red)" : "var(--muted)" }}>
            {picks.roi_pct != null ? `${picks.roi_pct > 0 ? "+" : ""}${picks.roi_pct.toFixed(1)}%` : "—"}
          </div>
          <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 4 }}>
            {picks.picks_with_odds > 0 ? `on ${picks.picks_with_odds} picks with odds` : "1 unit per pick"}
          </div>
        </div>
      </div>

      {/* ── Context note under hero (when OVER/UNDER edge diverge significantly) ── */}
      {picks.total > 0 && overRow && underRow && (() => {
        const oHr = pct(overRow.hits, overRow.total);
        const uHr = pct(underRow.hits, underRow.total);
        const gap = Math.abs(uHr - oHr);
        if (gap >= 8) {
          return (
            <div style={{ marginBottom: 16, padding: "8px 14px", background: "rgba(240,185,11,0.07)", borderRadius: 6, borderLeft: "3px solid var(--accent)", fontSize: 12, color: "var(--muted)" }}>
              ℹ️ The overall numbers above blend OVER and UNDER picks together.{" "}
              <strong style={{ color: "var(--text)" }}>
                OVER: {oHr}% · UNDER: {uHr}%
              </strong>
              {" "}— see the breakdown below.
            </div>
          );
        }
        return null;
      })()}

      {/* ── OVER vs UNDER Track Record — side-by-side ── */}
      {(overRow || underRow) && (
        <div style={{ ...CARD, marginBottom: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4, flexWrap: "wrap" }}>
            <span style={{ fontSize: 15, fontWeight: 700 }}>Pick Performance by Side</span>
            <span style={{ fontSize: 11, background: "var(--surface2)", color: "var(--muted)", borderRadius: 4, padding: "2px 8px" }}>
              {minScore}+ score · market breakeven ≈ {impliedPct.toFixed(1)}%
            </span>
          </div>
          <p style={{ margin: "0 0 14px", fontSize: 12, color: "var(--muted)" }}>
            OVER and UNDER picks are scored and recommended independently. Edge vs market is hit rate minus the bookmaker&apos;s implied probability.
          </p>
          <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr", gap: 12 }}>
            {[
              { label: "OVER", icon: "🔼", row: overRow },
              { label: "UNDER", icon: "🔽", row: underRow },
            ].map(({ label, icon, row }) => {
              if (!row || row.total === 0) return (
                <div key={label} style={{ ...CARD, padding: 16, opacity: 0.5 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>{icon} {label} Picks</div>
                  <div style={{ color: "var(--muted)", fontSize: 12 }}>No data</div>
                </div>
              );
              const hr       = pct(row.hits, row.total);
              const edgePp   = hr - impliedPct;
              const isPos    = edgePp > 0;
              const edgeColor = isPos ? "var(--green)" : "var(--red)";
              return (
                <div key={label} style={{
                  ...CARD, padding: 16,
                  borderColor: isPos ? "var(--green)" : "var(--border)",
                  borderWidth: isPos ? 2 : 1,
                }}>
                  <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12, color: isPos ? "var(--green)" : "var(--text)" }}>
                    {icon} {label} Picks
                  </div>
                  <div style={{ fontSize: 32, fontWeight: 800, color: pctColor(hr), lineHeight: 1, marginBottom: 4 }}>
                    {hr}%
                  </div>
                  <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 10 }}>
                    {row.hits} hits / {row.total} picks
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span style={{ fontSize: 14, fontWeight: 700, color: edgeColor }}>
                      {edgePp > 0 ? "+" : ""}{edgePp.toFixed(1)}pp
                    </span>
                    <span style={{ fontSize: 11, color: "var(--muted)" }}>vs market implied</span>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Insight callout when one side dominates */}
          {(() => {
            const oHr = overRow  ? pct(overRow.hits,  overRow.total)  : 0;
            const uHr = underRow ? pct(underRow.hits, underRow.total) : 0;
            const oEdge = oHr - impliedPct;
            const uEdge = uHr - impliedPct;
            if (underRow && underRow.total >= 20 && uEdge > 5 && uEdge - oEdge > 8) {
              return (
                <div style={{ marginTop: 12, padding: "10px 12px", background: "rgba(46,160,67,0.08)", borderRadius: 6, borderLeft: "3px solid var(--green)", fontSize: 12 }}>
                  <strong style={{ color: "var(--green)" }}>💡 Model strength: UNDER picks</strong>
                  <span style={{ color: "var(--muted)", marginLeft: 6 }}>
                    UNDER recommendations are outperforming OVERs by {(uEdge - oEdge).toFixed(1)}pp vs the market.
                    Focus on high-scored UNDER picks for the best edge.
                  </span>
                </div>
              );
            }
            if (overRow && overRow.total >= 20 && oEdge > 5 && oEdge - uEdge > 8) {
              return (
                <div style={{ marginTop: 12, padding: "10px 12px", background: "rgba(46,160,67,0.08)", borderRadius: 6, borderLeft: "3px solid var(--green)", fontSize: 12 }}>
                  <strong style={{ color: "var(--green)" }}>💡 Model strength: OVER picks</strong>
                  <span style={{ color: "var(--muted)", marginLeft: 6 }}>
                    OVER recommendations are outperforming UNDERs by {(oEdge - uEdge).toFixed(1)}pp vs the market.
                  </span>
                </div>
              );
            }
            return null;
          })()}
        </div>
      )}

      {/* ── Threshold Comparison Table ── */}
      {threshold_table && threshold_table.length > 0 && (
        <div style={{ ...CARD, marginBottom: 16 }}>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>Score Threshold Comparison</div>
          <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 12 }}>
            How performance changes as you raise the minimum score. Higher thresholds = fewer picks but more edge.
            Highlighted row = current active threshold.
          </div>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: isMobile ? 11 : 12 }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border)", color: "var(--muted)", fontSize: 10, textTransform: "uppercase" }}>
                  <th style={{ textAlign: "left", padding: "4px 8px", fontWeight: 600 }}>Min Score</th>
                  <th style={{ textAlign: "right", padding: "4px 8px", fontWeight: 600 }}>Picks</th>
                  <th style={{ textAlign: "right", padding: "4px 8px", fontWeight: 600 }}>Hit Rate</th>
                  <th style={{ textAlign: "right", padding: "4px 8px", fontWeight: 600 }}>Implied</th>
                  <th style={{ textAlign: "right", padding: "4px 8px", fontWeight: 600 }}>Edge</th>
                  <th style={{ textAlign: "right", padding: "4px 8px", fontWeight: 600 }}>ROI</th>
                </tr>
              </thead>
              <tbody>
                {[...threshold_table].reverse().map(row => {
                  const isActive = row.min_score === minScore;
                  const edgeColor = row.edge_pct != null
                    ? row.edge_pct > 0 ? "var(--green)" : "var(--red)"
                    : "var(--muted)";
                  return (
                    <tr
                      key={row.min_score}
                      style={{
                        borderBottom: "1px solid var(--border)",
                        background: isActive ? "rgba(240,185,11,0.08)" : "transparent",
                        fontWeight: isActive ? 700 : 400,
                      }}
                    >
                      <td style={{ padding: "6px 8px" }}>
                        <span style={{
                          display: "inline-flex", alignItems: "center", gap: 6,
                        }}>
                          {row.min_score}+
                          {isActive && (
                            <span style={{ fontSize: 9, background: "var(--accent)", color: "#0d1117", borderRadius: 3, padding: "1px 5px", fontWeight: 700 }}>
                              active
                            </span>
                          )}
                        </span>
                      </td>
                      <td style={{ textAlign: "right", padding: "6px 8px", color: "var(--muted)" }}>{row.total}</td>
                      <td style={{ textAlign: "right", padding: "6px 8px", color: pctColor(row.hit_rate_pct) }}>
                        {row.total > 0 ? `${row.hit_rate_pct.toFixed(1)}%` : "—"}
                      </td>
                      <td style={{ textAlign: "right", padding: "6px 8px", color: "var(--muted)" }}>
                        {row.implied_prob_pct != null ? `${row.implied_prob_pct.toFixed(1)}%` : "—"}
                      </td>
                      <td style={{ textAlign: "right", padding: "6px 8px", color: edgeColor, fontWeight: 600 }}>
                        {row.edge_pct != null
                          ? `${row.edge_pct > 0 ? "+" : ""}${row.edge_pct.toFixed(1)}pp`
                          : "—"}
                      </td>
                      <td style={{ textAlign: "right", padding: "6px 8px", color: row.roi_pct != null ? row.roi_pct > 0 ? "var(--green)" : "var(--red)" : "var(--muted)" }}>
                        {row.roi_pct != null
                          ? `${row.roi_pct > 0 ? "+" : ""}${row.roi_pct.toFixed(1)}%`
                          : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {noData ? (
        <div style={{ ...CARD, padding: "60px 20px", textAlign: "center", color: "var(--muted)" }}>
          No graded picks yet. Refresh props → let games finish → check results.
        </div>
      ) : (
        <>
          {/* ── Cumulative ROI Chart — the proof chart ── */}
          {cumulativePnlData.length > 1 && (
            <div style={{ ...CARD, marginBottom: 16 }}>
              <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>Cumulative ROI</div>
              <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 12 }}>
                Flat-stake returns over time (1 unit per pick, using actual odds). Trending up = model has edge.
              </div>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={cumulativePnlData} margin={{ left: 0, right: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="date" tick={{ fill: "var(--muted)", fontSize: 10 }} />
                  <YAxis tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={v => `${v > 0 ? "+" : ""}${v}u`} />
                  <Tooltip
                    contentStyle={{ background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 6 }}
                    formatter={(v: number | undefined) => [
                      v != null ? `${v > 0 ? "+" : ""}${v} units` : "—",
                      "Cumulative ROI",
                    ]}
                  />
                  <ReferenceLine y={0} stroke="var(--muted)" strokeDasharray="4 4" />
                  <Line
                    type="monotone" dataKey="cumulative_roi"
                    stroke={cumulativePnlData[cumulativePnlData.length - 1]?.cumulative_roi >= 0 ? "var(--green)" : "var(--red)"}
                    strokeWidth={2} dot={false} name="cumulative_roi"
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* ── Admin-only diagnostic sections ── */}
          {admin && (
            <>
              {/* ── Row 1: Value Score Calibration + Daily Trend ── */}
              <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr", gap: 16, marginBottom: 16 }}>
                {/* Value Score Calibration */}
                <div style={CARD}>
                  <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>Value Score Calibration</div>
                  <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 12 }}>
                    Hit rate by value score bucket — does a higher score mean more hits?
                  </div>
                  <ResponsiveContainer width="100%" height={240}>
                    <BarChart data={valCalData} margin={{ left: 0, right: 10 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                      <XAxis dataKey="bucket" tick={{ fill: "var(--muted)", fontSize: 10 }} />
                      <YAxis domain={[0, 100]} tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={v => `${v}%`} />
                      <Tooltip
                        contentStyle={{ background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 6 }}
                        formatter={(v, _, p) => [
                          `${v}% (${(p.payload as Record<string, number>).hits}/${(p.payload as Record<string, number>).sample})`, "Hit Rate"
                        ]}
                      />
                      <ReferenceLine y={50} stroke="var(--muted)" strokeDasharray="4 4" label={{ value: "50%", fill: "var(--muted)", fontSize: 10 }} />
                      <Bar dataKey="actual_pct" fill="var(--accent)" radius={[3, 3, 0, 0]} name="Hit %" />
                    </BarChart>
                  </ResponsiveContainer>
                  {/* Edge table per score bucket */}
                  {value_calibration.some(r => r.edge_pct != null) ? (
                    <div style={{ marginTop: 12 }}>
                      <div style={{ display: "grid", gridTemplateColumns: "60px 44px 70px 80px 60px 60px", gap: "0 4px", fontSize: 10, color: "var(--muted)", fontWeight: 600, padding: "4px 0", borderBottom: "1px solid var(--border)", marginBottom: 2 }}>
                        <span>Score</span><span>Picks</span><span>Hit Rate</span><span>Implied</span><span>Edge</span><span>ROI</span>
                      </div>
                      {[...value_calibration].reverse().map(r => {
                        const hr = r.total ? Math.round(r.hits / r.total * 100) : 0;
                        const edgeVal = r.edge_pct;
                        const roiVal  = r.roi_pct;
                        const edgeColor = edgeVal != null ? edgeVal > 0 ? "var(--green)" : "var(--red)" : "var(--muted)";
                        return (
                          <div key={r.bucket} style={{ display: "grid", gridTemplateColumns: "60px 44px 70px 80px 60px 60px", gap: "0 4px", fontSize: 11, padding: "3px 0", borderBottom: "1px solid var(--border)" }}>
                            <span style={{ color: "var(--muted)" }}>{r.bucket}–{r.bucket + 4}</span>
                            <span>{r.total}</span>
                            <span style={{ color: pctColor(hr) }}>{hr}%</span>
                            <span style={{ color: "var(--muted)" }}>{r.avg_implied_prob != null ? `${Math.round(r.avg_implied_prob * 100)}%` : "—"}</span>
                            <span style={{ color: edgeColor, fontWeight: 600 }}>{edgeVal != null ? `${edgeVal > 0 ? "+" : ""}${edgeVal.toFixed(1)}pp` : "—"}</span>
                            <span style={{ color: roiVal != null ? roiVal > 0 ? "var(--green)" : "var(--red)" : "var(--muted)" }}>{roiVal != null ? `${roiVal > 0 ? "+" : ""}${roiVal.toFixed(1)}%` : "—"}</span>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div style={{ marginTop: 8 }}>
                      {valCalData.map(r => (
                        <div key={r.bucket} style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--muted)", marginBottom: 2 }}>
                          <span>Score {r.bucket}</span>
                          <span style={{ color: pctColor(r.actual_pct) }}>
                            {r.actual_pct}% hit rate <span style={{ color: "var(--muted)" }}>(n={r.sample})</span>
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Daily Trend */}
                <div style={CARD}>
                  <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>Daily Hit Rate Trend</div>
                  <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 12 }}>
                    How picks are performing day-over-day.
                  </div>
                  {trendData.length > 1 ? (
                    <ResponsiveContainer width="100%" height={240}>
                      <LineChart data={trendData} margin={{ left: 0, right: 20 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                        <XAxis dataKey="date" tick={{ fill: "var(--muted)", fontSize: 10 }} />
                        <YAxis domain={[0, 100]} tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={v => `${v}%`} />
                        <Tooltip
                          contentStyle={{ background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 6 }}
                          formatter={(v, _, p) => [
                            `${v}% (${(p.payload as Record<string, number>).hits}/${(p.payload as Record<string, number>).total})`, "Hit Rate"
                          ]}
                        />
                        <ReferenceLine y={50} stroke="var(--muted)" strokeDasharray="4 4" />
                        <Line type="monotone" dataKey="hit_pct" stroke="var(--accent)" strokeWidth={2} dot={{ fill: "var(--accent)", r: 4 }} name="Hit %" />
                      </LineChart>
                    </ResponsiveContainer>
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 8, paddingTop: 20 }}>
                      {trendData.map(r => (
                        <div key={r.date} style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                          <span>{r.date}</span>
                          <span style={{ color: pctColor(r.hit_pct), fontWeight: 600 }}>
                            {r.hit_pct}% ({r.hits}/{r.total})
                          </span>
                        </div>
                      ))}
                      <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 8 }}>
                        Line chart will appear after 2+ days of data.
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* ── Row 2: Hit rate by Market + Factor Summary Table ── */}
              <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr", gap: 16, marginBottom: 16 }}>
                {/* Market breakdown */}
                {by_market.length > 0 && (
                  <div style={CARD}>
                    <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>Hit Rate by Market</div>
                    <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 12 }}>Sorted by hit rate. Edge and ROI show where the model has the most value.</div>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 44px 70px 60px 60px", gap: "0 8px", fontSize: 10, color: "var(--muted)", fontWeight: 600, padding: "4px 0", borderBottom: "1px solid var(--border)", marginBottom: 2 }}>
                      <span>Market</span><span>Picks</span><span>Hit Rate</span><span>Edge</span><span>ROI</span>
                    </div>
                    {by_market.map(r => {
                      const hr = r.total ? Math.round(r.hits / r.total * 100) : 0;
                      return (
                        <div key={r.market_label} style={{ display: "grid", gridTemplateColumns: "1fr 44px 70px 60px 60px", gap: "0 8px", fontSize: 12, padding: "5px 0", borderBottom: "1px solid var(--border)", alignItems: "center" }}>
                          <span>{r.market_label}</span>
                          <span style={{ color: "var(--muted)" }}>{r.total}</span>
                          <div>
                            <div style={{ height: 4, background: "var(--surface2)", borderRadius: 2, marginBottom: 2 }}>
                              <div style={{ width: `${hr}%`, height: "100%", background: pctColor(hr), borderRadius: 2 }} />
                            </div>
                            <span style={{ fontSize: 10, color: pctColor(hr) }}>{hr}%</span>
                          </div>
                          <span style={{ fontWeight: 600, color: r.edge_pct != null ? r.edge_pct > 0 ? "var(--green)" : "var(--red)" : "var(--muted)", fontSize: 11 }}>
                            {r.edge_pct != null ? `${r.edge_pct > 0 ? "+" : ""}${r.edge_pct.toFixed(1)}pp` : "—"}
                          </span>
                          <span style={{ color: r.roi_pct != null ? r.roi_pct > 0 ? "var(--green)" : "var(--red)" : "var(--muted)", fontSize: 11 }}>
                            {r.roi_pct != null ? `${r.roi_pct > 0 ? "+" : ""}${r.roi_pct.toFixed(1)}%` : "—"}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* Factor Summary Table */}
                <div style={CARD}>
                  <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>Factor Performance Summary</div>
                  <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 12 }}>
                    Overall hit rate vs. high-score (60+) hit rate per factor.
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 90px 90px", gap: 0, fontSize: 11, color: "var(--muted)", padding: "6px 0", borderBottom: "1px solid var(--border)", fontWeight: 600 }}>
                    <span>Factor</span>
                    <span>Overall</span>
                    <span>Score 60+</span>
                  </div>
                  {factorSummary.map(f => (
                    <div
                      key={f.name}
                      style={{
                        display: "grid", gridTemplateColumns: "1fr 90px 90px", gap: 0,
                        fontSize: 12, padding: "6px 0", borderBottom: "1px solid var(--border)",
                        cursor: "pointer",
                        background: activeFactor === f.name ? "var(--surface2)" : "transparent",
                      }}
                      onClick={() => setActiveFactor(f.name)}
                    >
                      <span style={{ fontWeight: activeFactor === f.name ? 600 : 400 }}>{f.name}</span>
                      <span style={{ color: pctColor(f.overall_pct) }}>
                        {f.overall_pct}% <span style={{ color: "var(--muted)" }}>({f.overall_n})</span>
                      </span>
                      <span style={{ color: pctColor(f.high_pct) }}>
                        {f.high_n > 0 ? `${f.high_pct}%` : "—"} <span style={{ color: "var(--muted)" }}>({f.high_n})</span>
                      </span>
                    </div>
                  ))}
                  <div style={{ fontSize: 10, color: "var(--muted)", marginTop: 8 }}>
                    Click a factor to see its calibration chart below.
                  </div>
                </div>
              </div>

              {/* ── Row 3: Factor Calibration Chart ── */}
              <div style={CARD}>
                <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12, flexWrap: "wrap" }}>
                  <div style={{ fontSize: 14, fontWeight: 600 }}>Factor Calibration: {activeFactor}</div>
                  <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                    {FACTOR_ORDER.map(f => (
                      <button key={f} style={pill(activeFactor === f)} onClick={() => setActiveFactor(f)}>
                        {f}
                      </button>
                    ))}
                  </div>
                </div>
                <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 12 }}>
                  If the factor is well-calibrated, actual hit rate (orange) should follow the ideal line (grey).
                  Divergence means the factor score doesn&apos;t predict hit rate at that level.
                </div>
                {activeFactorData.length > 0 ? (
                  <>
                    <ResponsiveContainer width="100%" height={250}>
                      <LineChart data={activeFactorData} margin={{ left: 0, right: 20 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                        <XAxis dataKey="bucket" tick={{ fill: "var(--muted)", fontSize: 10 }} />
                        <YAxis domain={[0, 100]} tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={v => `${v}%`} />
                        <Tooltip
                          contentStyle={{ background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 6 }}
                          formatter={(v) => [`${v}%`]}
                        />
                        <Legend wrapperStyle={{ fontSize: 11, color: "var(--muted)" }} />
                        <Line type="monotone" dataKey="actual_pct" stroke="var(--accent)" strokeWidth={2} dot={{ fill: "var(--accent)", r: 4 }} name="Actual Hit %" />
                        <Line type="monotone" dataKey="ideal" stroke="var(--border)" strokeWidth={1} strokeDasharray="4 4" dot={false} name="Perfect Calibration" />
                      </LineChart>
                    </ResponsiveContainer>
                    <div style={{ marginTop: 8, display: "grid", gridTemplateColumns: "1fr 1fr", gap: "2px 24px" }}>
                      {activeFactorData.map(r => (
                        <div key={r.bucket} style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--muted)" }}>
                          <span>{r.bucket}</span>
                          <span style={{ color: pctColor(r.actual_pct) }}>
                            {r.actual_pct}% <span style={{ color: "var(--muted)" }}>(n={r.sample})</span>
                          </span>
                        </div>
                      ))}
                    </div>
                  </>
                ) : (
                  <div style={{ color: "var(--muted)", padding: 20, textAlign: "center", fontSize: 13 }}>
                    No data for {activeFactor} — check results first.
                  </div>
                )}
              </div>

              {/* ── Slip Stats (secondary) ── */}
              {slips.total_slips > 0 && (
                <div style={{ marginTop: 16 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "var(--muted)", marginBottom: 8 }}>Bet Slip Stats</div>
                  <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "repeat(3, 1fr)", gap: 12 }}>
                    <div style={CARD}>
                      <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Slips Recorded</div>
                      <div style={{ fontSize: 20, fontWeight: 700 }}>{slips.total_slips}</div>
                    </div>
                    <div style={CARD}>
                      <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Slip Win Rate</div>
                      <div style={{ fontSize: 20, fontWeight: 700, color: slips.win_rate >= 0.5 ? "var(--green)" : "var(--red)" }}>
                        {(slips.win_rate * 100).toFixed(1)}%
                      </div>
                    </div>
                    <div style={CARD}>
                      <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Total P&L</div>
                      <div style={{ fontSize: 20, fontWeight: 700, color: slips.total_pnl >= 0 ? "var(--green)" : "var(--red)" }}>
                        {slips.total_pnl >= 0 ? "+" : ""}{slips.total_pnl.toFixed(2)}
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
