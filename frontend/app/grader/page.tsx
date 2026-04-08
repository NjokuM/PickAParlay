"use client";

import { useEffect, useState, useMemo } from "react";
import { api, Prop, TonightPlayer, Game } from "@/lib/api";
import { FactorGrid } from "@/components/FactorBar";
import { ScoreBadge, RecoBadge } from "@/components/Badge";
import { PlayerHeadshot } from "@/components/PlayerHeadshot";
import { useIsMobile } from "@/hooks/useIsMobile";

const MARKET_OPTIONS = [
  { label: "Points", value: "player_points" },
  { label: "Assists", value: "player_assists" },
  { label: "Rebounds", value: "player_rebounds" },
  { label: "3PM", value: "player_threes" },
  { label: "PRA", value: "player_points_rebounds_assists" },
  { label: "P+R", value: "player_points_rebounds" },
  { label: "P+A", value: "player_points_assists" },
  { label: "R+A", value: "player_rebounds_assists" },
];

export default function GraderPage() {
  const isMobile = useIsMobile();
  const [players, setPlayers] = useState<TonightPlayer[]>([]);
  const [games, setGames] = useState<Game[]>([]);
  const [browseGame, setBrowseGame] = useState<Game | null>(null);
  const [selected, setSelected] = useState<TonightPlayer | null>(null);
  const [search, setSearch] = useState("");
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [market, setMarket] = useState(MARKET_OPTIONS[0].value);
  const [line, setLine] = useState<string>("10.5");
  const [side, setSide] = useState<"over" | "under">("over");
  const [result, setResult] = useState<Prop | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [playersLoading, setPlayersLoading] = useState(true);

  useEffect(() => {
    api.tonightPlayers()
      .then(setPlayers)
      .catch(() => {})
      .finally(() => setPlayersLoading(false));
    api.tonight().then(setGames).catch(() => {});
  }, []);

  const browsePlayers = useMemo(() => {
    if (!browseGame) return [];
    return players
      .filter(p => p.team === browseGame.home_team || p.team === browseGame.away_team)
      .sort((a, b) => a.player_name.localeCompare(b.player_name));
  }, [players, browseGame]);

  const browseGrouped = useMemo(() => {
    if (!browseGame) return [];
    const away = browsePlayers.filter(p => p.team === browseGame.away_team);
    const home = browsePlayers.filter(p => p.team === browseGame.home_team);
    return [
      { team: browseGame.away_team, players: away },
      { team: browseGame.home_team, players: home },
    ];
  }, [browsePlayers, browseGame]);

  // Search dropdown filtering (independent of browse)
  const searchFiltered = players.filter(
    (p) =>
      search.length >= 2 &&
      (p.player_name.toLowerCase().includes(search.toLowerCase()) ||
        p.team.toLowerCase().includes(search.toLowerCase()))
  );

  async function handleGrade() {
    if (!selected) return;
    const parsedLine = parseFloat(line);
    if (isNaN(parsedLine) || parsedLine < 0) {
      setError("Enter a valid line (e.g. 10.5)");
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.gradeCustom({
        player_name: selected.player_name,
        player_id: selected.player_id,
        market,
        line: parsedLine,
        side,
      });
      setResult(res);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Grading failed";
      try {
        const parsed = JSON.parse(msg);
        setError(parsed.detail || msg);
      } catch {
        setError(msg);
      }
    } finally {
      setLoading(false);
    }
  }

  function adjustLine(delta: number) {
    const current = parseFloat(line) || 0;
    const next = Math.max(0.5, +(current + delta).toFixed(1));
    setLine(String(next));
  }

  function selectPlayer(p: TonightPlayer) {
    setSelected(p);
    setSearch("");
    setDropdownOpen(false);
    setResult(null);
  }

  const labelStyle: React.CSSProperties = {
    fontSize: 11, fontWeight: 600, color: "var(--muted)", marginBottom: 6,
    display: "block", textTransform: "uppercase", letterSpacing: "0.5px",
  };

  const marketLabel = MARKET_OPTIONS.find(m => m.value === market)?.label ?? market;

  return (
    <div style={{ maxWidth: 900, margin: "0 auto" }}>
      <div style={{ marginBottom: 16 }}>
        <h1 style={{ fontSize: isMobile ? 18 : 22, fontWeight: 700, marginBottom: 2 }}>
          Custom Prop Grader
        </h1>
        <p style={{ fontSize: 12, color: "var(--muted)", margin: 0 }}>
          Grade any player prop through the 8-factor model.
        </p>
      </div>

      <div style={{
        display: "flex", gap: 16,
        flexDirection: isMobile ? "column" : "row",
        alignItems: "flex-start",
      }}>
        {/* ── Left: Player Browser ── */}
        <div style={{
          width: isMobile ? "100%" : 280, flexShrink: 0,
          background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10,
          overflow: "hidden",
        }}>
          <div style={{ padding: "10px 12px", borderBottom: "1px solid var(--border)" }}>
            <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>
              Tonight&apos;s Games
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {games.map((g) => {
                const active = browseGame?.game_id === g.game_id;
                return (
                  <button
                    key={g.game_id}
                    onClick={() => setBrowseGame(active ? null : g)}
                    style={{
                      padding: "6px 10px", borderRadius: 6, fontSize: 12, fontWeight: 600,
                      cursor: "pointer", transition: "all 0.15s", textAlign: "left",
                      border: active ? "1px solid var(--accent)" : "1px solid var(--border)",
                      background: active ? "rgba(88,166,255,0.12)" : "var(--bg)",
                      color: active ? "var(--accent)" : "var(--text)",
                      display: "flex", justifyContent: "center",
                    }}
                  >
                    <span>{g.away_team}</span>
                    <span style={{ color: "var(--muted)", margin: "0 4px", fontWeight: 400 }}>@</span>
                    <span>{g.home_team}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Player list for selected game */}
          {browseGame && (
            <div style={{ maxHeight: isMobile ? 250 : 400, overflowY: "auto" }}>
              {browseGrouped.map(({ team, players: pls }) => (
                <div key={team}>
                  <div style={{
                    padding: "5px 12px", fontSize: 11, fontWeight: 700, color: "var(--accent)",
                    background: "var(--surface2)", textTransform: "uppercase", letterSpacing: "0.5px",
                    position: "sticky", top: 0, zIndex: 1,
                  }}>{team}</div>
                  {pls.map(p => {
                    const isActive = selected?.player_id === p.player_id;
                    return (
                      <div
                        key={p.player_id}
                        onClick={() => selectPlayer(p)}
                        style={{
                          padding: "5px 12px", cursor: "pointer", fontSize: 12,
                          display: "flex", alignItems: "center", gap: 7,
                          background: isActive ? "rgba(88,166,255,0.1)" : "transparent",
                          borderLeft: isActive ? "2px solid var(--accent)" : "2px solid transparent",
                          transition: "all 0.1s",
                        }}
                        onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.background = "var(--surface2)"; }}
                        onMouseLeave={(e) => { if (!isActive) e.currentTarget.style.background = isActive ? "rgba(88,166,255,0.1)" : "transparent"; }}
                      >
                        <PlayerHeadshot playerId={p.player_id} size={20} />
                        <span style={{
                          fontWeight: isActive ? 600 : 400,
                          color: isActive ? "var(--accent)" : "var(--text)",
                        }}>{p.player_name}</span>
                      </div>
                    );
                  })}
                </div>
              ))}
            </div>
          )}

          {!browseGame && (
            <div style={{ padding: "16px 12px", fontSize: 12, color: "var(--muted)", textAlign: "center" }}>
              Pick a game to browse players
            </div>
          )}
        </div>

        {/* ── Right: Grader Form (always visible) ── */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10,
            padding: isMobile ? 12 : 16, marginBottom: 12,
          }}>
            {/* Player field */}
            <div style={{ position: "relative", marginBottom: 14 }}>
              <label style={labelStyle}>Player</label>
              {selected ? (
                <div style={{
                  padding: "8px 12px", borderRadius: 8,
                  border: "1px solid var(--accent)", background: "var(--surface2)",
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                }}>
                  <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <PlayerHeadshot playerId={selected.player_id} size={24} />
                    <span style={{ fontWeight: 600, fontSize: 14 }}>{selected.player_name}</span>
                    <span style={{
                      fontSize: 10, color: "var(--muted)", background: "var(--bg)",
                      padding: "1px 5px", borderRadius: 3,
                    }}>{selected.team}</span>
                  </span>
                  <button
                    onClick={() => { setSelected(null); setResult(null); setSearch(""); }}
                    style={{
                      background: "none", border: "none", color: "var(--muted)",
                      cursor: "pointer", fontSize: 14, padding: "0 4px",
                    }}
                  >&times;</button>
                </div>
              ) : (
                <>
                  <input
                    value={search}
                    onChange={(e) => { setSearch(e.target.value); setDropdownOpen(true); }}
                    onFocus={() => setDropdownOpen(true)}
                    onBlur={() => setTimeout(() => setDropdownOpen(false), 200)}
                    placeholder={playersLoading ? "Loading players..." : "Search any player..."}
                    disabled={playersLoading}
                    style={{
                      padding: "8px 12px", borderRadius: 8, border: "1px solid var(--border)",
                      background: "var(--bg)", color: "var(--text)", fontSize: 13,
                      width: "100%", outline: "none",
                    }}
                  />
                  {dropdownOpen && searchFiltered.length > 0 && (
                    <div style={{
                      position: "absolute", top: "100%", left: 0, right: 0, zIndex: 50,
                      background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8,
                      maxHeight: 220, overflowY: "auto", marginTop: 4,
                      boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
                    }}>
                      {searchFiltered.slice(0, 20).map((p) => (
                        <div
                          key={p.player_id}
                          onMouseDown={() => selectPlayer(p)}
                          style={{
                            padding: "7px 12px", cursor: "pointer", fontSize: 13,
                            borderBottom: "1px solid var(--border)",
                            display: "flex", alignItems: "center", gap: 8,
                          }}
                          onMouseEnter={(e) => (e.currentTarget.style.background = "var(--surface2)")}
                          onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                        >
                          <PlayerHeadshot playerId={p.player_id} size={22} />
                          <span style={{ fontWeight: 500 }}>{p.player_name}</span>
                          <span style={{
                            fontSize: 10, color: "var(--muted)", marginLeft: "auto",
                            background: "var(--bg)", padding: "1px 5px", borderRadius: 3,
                          }}>{p.team}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>

            {/* Market pills */}
            <div style={{ marginBottom: 14 }}>
              <label style={labelStyle}>Market</label>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                {MARKET_OPTIONS.map((m) => (
                  <button
                    key={m.value}
                    onClick={() => setMarket(m.value)}
                    style={{
                      padding: "5px 12px", borderRadius: 16, fontSize: 12, fontWeight: 500,
                      cursor: "pointer", transition: "all 0.15s", whiteSpace: "nowrap",
                      border: market === m.value ? "1px solid var(--accent)" : "1px solid var(--border)",
                      background: market === m.value ? "rgba(88,166,255,0.12)" : "var(--bg)",
                      color: market === m.value ? "var(--accent)" : "var(--muted)",
                    }}
                  >{m.label}</button>
                ))}
              </div>
            </div>

            {/* Line + Side */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
              <div>
                <label style={labelStyle}>Line</label>
                <div style={{ display: "flex" }}>
                  <button
                    onClick={() => adjustLine(-1)}
                    style={{
                      width: 34,
                      borderTop: "1px solid var(--border)", borderBottom: "1px solid var(--border)",
                      borderLeft: "1px solid var(--border)", borderRight: "none",
                      borderRadius: "6px 0 0 6px", background: "var(--bg)", color: "var(--muted)",
                      fontSize: 16, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.background = "var(--surface2)"; }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = "var(--bg)"; }}
                  >&minus;</button>
                  <input
                    type="number"
                    step="0.5"
                    min="0"
                    value={line}
                    onChange={(e) => setLine(e.target.value)}
                    style={{
                      flex: 1, padding: "8px 4px", border: "1px solid var(--border)",
                      borderRadius: 0, background: "var(--bg)", color: "var(--text)",
                      fontSize: 15, fontWeight: 600, textAlign: "center", outline: "none",
                      width: "100%", minWidth: 0,
                    }}
                  />
                  <button
                    onClick={() => adjustLine(1)}
                    style={{
                      width: 34,
                      borderTop: "1px solid var(--border)", borderBottom: "1px solid var(--border)",
                      borderRight: "1px solid var(--border)", borderLeft: "none",
                      borderRadius: "0 6px 6px 0", background: "var(--bg)", color: "var(--muted)",
                      fontSize: 16, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.background = "var(--surface2)"; }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = "var(--bg)"; }}
                  >+</button>
                </div>
              </div>
              <div>
                <label style={labelStyle}>Side</label>
                <div style={{ display: "flex" }}>
                  {(["over", "under"] as const).map((s, i) => (
                    <button
                      key={s}
                      onClick={() => setSide(s)}
                      style={{
                        flex: 1, padding: "8px 0",
                        borderRadius: i === 0 ? "6px 0 0 6px" : "0 6px 6px 0",
                        fontSize: 12, fontWeight: 700, letterSpacing: "0.5px",
                        cursor: "pointer", transition: "all 0.15s",
                        borderTop: side === s
                          ? `1px solid ${s === "over" ? "var(--accent)" : "var(--orange)"}`
                          : "1px solid var(--border)",
                        borderBottom: side === s
                          ? `1px solid ${s === "over" ? "var(--accent)" : "var(--orange)"}`
                          : "1px solid var(--border)",
                        borderRight: side === s
                          ? `1px solid ${s === "over" ? "var(--accent)" : "var(--orange)"}`
                          : "1px solid var(--border)",
                        borderLeft: i === 1 ? "none"
                          : side === s
                            ? `1px solid ${s === "over" ? "var(--accent)" : "var(--orange)"}`
                            : "1px solid var(--border)",
                        background: side === s
                          ? s === "over" ? "rgba(88,166,255,0.15)" : "rgba(210,153,34,0.15)"
                          : "var(--bg)",
                        color: side === s
                          ? s === "over" ? "var(--accent)" : "var(--orange)"
                          : "var(--muted)",
                      }}
                    >{s.toUpperCase()}</button>
                  ))}
                </div>
              </div>
            </div>

            {/* Grade button */}
            <button
              onClick={handleGrade}
              disabled={!selected || loading}
              style={{
                width: "100%", padding: "10px 0", borderRadius: 8, fontSize: 14, fontWeight: 700,
                border: "none", cursor: selected && !loading ? "pointer" : "not-allowed",
                background: selected && !loading
                  ? "linear-gradient(135deg, var(--accent), #4090e0)"
                  : "var(--surface2)",
                color: selected && !loading ? "#fff" : "var(--muted)",
                transition: "all 0.2s",
                boxShadow: selected && !loading ? "0 2px 12px rgba(88,166,255,0.25)" : "none",
              }}
            >
              {loading ? "Grading..." : selected
                ? `Grade ${selected.player_name.split(" ").pop()} ${side.charAt(0).toUpperCase() + side.slice(1)} ${line} ${marketLabel}`
                : "Select a player to grade"}
            </button>
          </div>

          {/* Error */}
          {error && (
            <div style={{
              padding: "10px 14px", borderRadius: 8, marginBottom: 12,
              background: "rgba(248,81,73,0.08)", border: "1px solid rgba(248,81,73,0.3)",
              color: "var(--red)", fontSize: 12,
            }}>
              {error}
            </div>
          )}

          {/* Result */}
          {result && (
            <div style={{
              background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10,
              overflow: "hidden",
            }}>
              <div style={{ padding: isMobile ? 12 : 16, borderBottom: "1px solid var(--border)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
                  <PlayerHeadshot playerId={result.player_id} size={isMobile ? 40 : 48} />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 700, fontSize: isMobile ? 15 : 17 }}>{result.player_name}</div>
                    <div style={{ fontSize: 11, color: "var(--muted)" }}>{result.game}</div>
                  </div>
                  <ScoreBadge score={result.value_score} />
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <span style={{
                    fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 4,
                    background: side === "under" ? "rgba(210,153,34,0.15)" : "rgba(88,166,255,0.15)",
                    color: side === "under" ? "var(--orange)" : "var(--accent)",
                    letterSpacing: "0.5px",
                  }}>{side.toUpperCase()}</span>
                  <span style={{ fontSize: 14, fontWeight: 700 }}>
                    {result.line} {result.market_label}
                  </span>
                  <RecoBadge reco={result.recommendation} />
                  {result.suspicious_line && (
                    <span style={{ fontSize: 10, color: "var(--orange)" }}>
                      &#9888; {result.suspicious_reason}
                    </span>
                  )}
                </div>
              </div>

              {result.backing_data && (
                <div style={{
                  padding: "10px 16px", borderBottom: "1px solid var(--border)",
                  display: "flex", gap: 12, flexWrap: "wrap",
                }}>
                  {Object.entries(result.backing_data).map(([k, v]) =>
                    typeof v !== "object" ? (
                      <span key={k} style={{ fontSize: 11, color: "var(--muted)" }}>
                        <strong style={{ color: "var(--text)" }}>{k.replace(/_/g, " ")}:</strong>{" "}
                        {String(v)}
                      </span>
                    ) : null
                  )}
                </div>
              )}

              <div style={{ padding: isMobile ? 12 : 16 }}>
                <FactorGrid factors={result.factors} />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
