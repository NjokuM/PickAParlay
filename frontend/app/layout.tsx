"use client";

import "./globals.css";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, Credits, ScheduleInfo } from "@/lib/api";
import { SlipBuilderProvider } from "@/lib/slip-builder-context";
import SlipBuilderPanel from "@/components/SlipBuilderPanel";
import { getUser, isLoggedIn, clearAuth, isAdmin, AuthUser } from "@/lib/auth";
import { useIsMobile } from "@/hooks/useIsMobile";

function timeAgo(isoStr: string): string {
  const diff = Date.now() - new Date(isoStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ${mins % 60}m ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function nextRunLabel(schedule: ScheduleInfo): string | null {
  const upcoming = schedule.jobs
    .filter(j => j.next_run)
    .sort((a, b) => new Date(a.next_run!).getTime() - new Date(b.next_run!).getTime());
  if (!upcoming.length) return null;
  const next = upcoming[0];
  const label = next.id === "grade_results" ? "Grade" :
                next.id === "morning_refresh" ? "Refresh" :
                next.id === "evening_refresh" ? "Refresh" : next.id;
  return `${label} @ ${next.next_run_human}`;
}

const NAV = [
  { href: "/",          label: "Tonight",   icon: "\u{1F3C0}" },
  { href: "/slips",     label: "Slips",     icon: "\u{1F3AF}" },
  { href: "/ladder",    label: "Ladder",    icon: "\u{1FA9C}" },
  { href: "/history",      label: "History",      icon: "\u{1F4CB}" },
  { href: "/prop-results", label: "Results", icon: "\u{1F4CA}" },
  { href: "/analytics",    label: "Analytics",    icon: "\u{1F4C8}" },
  { href: "/grader",       label: "Grader",       icon: "\u{1F9EA}" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const isMobile = useIsMobile();
  const [credits, setCredits] = useState<Credits | null>(null);
  const [schedule, setSchedule] = useState<ScheduleInfo | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    if (pathname === "/login") { setAuthChecked(true); return; }
    if (!isLoggedIn()) { router.push("/login"); return; }
    setUser(getUser());
    setAuthChecked(true);
    api.credits().then(setCredits).catch(() => {});
    api.schedule().then(setSchedule).catch(() => {});
  }, [pathname, router]);

  // Close mobile menu on navigation
  useEffect(() => { setMobileMenuOpen(false); }, [pathname]);

  if (pathname === "/login") {
    return (
      <html lang="en">
        <head>
          <title>PickAParlay - Login</title>
          <meta name="description" content="NBA Bet Builder" />
          <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1" />
        </head>
        <body style={{ margin: 0 }}>{children}</body>
      </html>
    );
  }

  if (!authChecked) {
    return (
      <html lang="en">
        <head><title>PickAParlay</title><meta name="viewport" content="width=device-width, initial-scale=1" /></head>
        <body style={{ margin: 0, background: "#0d1117" }} />
      </html>
    );
  }

  function handleLogout() { clearAuth(); router.push("/login"); }

  // ── Mobile Layout ──
  if (isMobile) {
    return (
      <html lang="en">
        <head>
          <title>PickAParlay</title>
          <meta name="description" content="NBA Bet Builder" />
          <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no" />
        </head>
        <body style={{ margin: 0 }}>
          <SlipBuilderProvider>
            {/* Top bar */}
            <header style={{
              position: "sticky", top: 0, zIndex: 100,
              display: "flex", alignItems: "center", justifyContent: "space-between",
              padding: "10px 16px",
              background: "var(--surface)", borderBottom: "1px solid var(--border)",
            }}>
              <div style={{ fontSize: 15, fontWeight: 700, color: "var(--accent)" }}>
                PickAParlay
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                {user && (
                  <span style={{ fontSize: 12, color: "var(--muted)" }}>
                    {user.display_name || user.username}
                  </span>
                )}
                <button
                  onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
                  style={{
                    background: "none", border: "none", color: "var(--text)",
                    fontSize: 20, cursor: "pointer", padding: "4px",
                  }}
                >
                  {mobileMenuOpen ? "✕" : "☰"}
                </button>
              </div>
            </header>

            {/* Dropdown menu */}
            {mobileMenuOpen && (
              <div style={{
                position: "fixed", top: 48, left: 0, right: 0, bottom: 0,
                zIndex: 99, background: "rgba(0,0,0,0.6)",
              }} onClick={() => setMobileMenuOpen(false)}>
                <div style={{
                  background: "var(--surface)", borderBottom: "1px solid var(--border)",
                  padding: "8px 0",
                }} onClick={e => e.stopPropagation()}>
                  {credits && user?.is_admin && (
                    <div style={{ padding: "8px 16px", fontSize: 11, color: "var(--muted)", borderBottom: "1px solid var(--border)" }}>
                      Odds API: {credits.used}/{credits.total} used · {credits.remaining} left{credits.total_keys && credits.total_keys > 1 ? ` (${credits.active_keys}/${credits.total_keys} keys)` : ""}
                    </div>
                  )}
                  {schedule && user?.is_admin && (
                    <div style={{ padding: "8px 16px", fontSize: 11, color: "var(--muted)", borderBottom: "1px solid var(--border)" }}>
                      {schedule.last_refresh && <>Refreshed: {timeAgo(schedule.last_refresh)}<br /></>}
                      {nextRunLabel(schedule) && <>Next: {nextRunLabel(schedule)}</>}
                    </div>
                  )}
                  <button onClick={handleLogout} style={{
                    display: "block", width: "100%", textAlign: "left",
                    padding: "12px 16px", background: "none", border: "none",
                    color: "var(--red)", fontSize: 14, cursor: "pointer",
                  }}>
                    Sign Out
                  </button>
                </div>
              </div>
            )}

            {/* Main content — padded for top bar + bottom nav */}
            <main style={{ padding: "16px 12px", paddingBottom: 80, minHeight: "calc(100vh - 48px)" }}>
              {children}
            </main>

            <SlipBuilderPanel />

            {/* Bottom tab bar */}
            <nav style={{
              position: "fixed", bottom: 0, left: 0, right: 0,
              zIndex: 90,
              display: "flex", justifyContent: "space-around",
              background: "var(--surface)", borderTop: "1px solid var(--border)",
              paddingBottom: "env(safe-area-inset-bottom, 0px)",
            }}>
              {NAV.map(({ href, label, icon }) => {
                const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
                return (
                  <Link key={href} href={href} style={{
                    display: "flex", flexDirection: "column", alignItems: "center",
                    padding: "8px 4px", gap: 2,
                    color: active ? "var(--accent)" : "var(--muted)",
                    textDecoration: "none", fontSize: 10, fontWeight: active ? 700 : 400,
                    flex: 1,
                  }}>
                    <span style={{ fontSize: 18 }}>{icon}</span>
                    <span>{label}</span>
                  </Link>
                );
              })}
            </nav>
          </SlipBuilderProvider>
        </body>
      </html>
    );
  }

  // ── Desktop Layout ──
  return (
    <html lang="en">
      <head>
        <title>PickAParlay</title>
        <meta name="description" content="NBA Bet Builder" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </head>
      <body style={{ margin: 0 }}>
        <div style={{ display: "flex", minHeight: "100vh" }}>
          {/* Sidebar */}
          <aside style={{
            width: 200,
            background: "var(--surface)",
            borderRight: "1px solid var(--border)",
            display: "flex",
            flexDirection: "column",
            padding: "0",
            flexShrink: 0,
          }}>
            <div style={{ padding: "20px 16px 16px", borderBottom: "1px solid var(--border)" }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: "var(--accent)" }}>PickAParlay</div>
              <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>NBA Prop Analytics</div>
            </div>

            <nav style={{ flex: 1, padding: "8px 0" }}>
              {NAV.map(({ href, label, icon }) => {
                const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
                return (
                  <Link key={href} href={href} style={{
                    display: "flex", alignItems: "center", gap: 10,
                    padding: "10px 16px",
                    color: active ? "var(--text)" : "var(--muted)",
                    background: active ? "var(--surface2)" : "transparent",
                    borderLeft: active ? "2px solid var(--accent)" : "2px solid transparent",
                    textDecoration: "none", fontSize: 14, transition: "all 0.1s",
                  }}>
                    <span>{icon}</span><span>{label}</span>
                  </Link>
                );
              })}
            </nav>

            {credits && user?.is_admin && (
              <div style={{ padding: "12px 16px", borderTop: "1px solid var(--border)", fontSize: 11, color: "var(--muted)" }}>
                <div>Odds API</div>
                <div style={{ marginTop: 4 }}>
                  <div style={{ height: 4, background: "var(--surface2)", borderRadius: 2, overflow: "hidden" }}>
                    <div style={{
                      width: `${(credits.used / credits.total) * 100}%`, height: "100%",
                      background: credits.remaining < 50 ? "var(--red)" : "var(--accent)",
                      transition: "width 0.3s",
                    }} />
                  </div>
                  <div style={{ marginTop: 4 }}>{credits.used}/{credits.total} used · {credits.remaining} left</div>
                </div>
              </div>
            )}

            {schedule && user?.is_admin && (
              <div style={{ padding: "12px 16px", borderTop: "1px solid var(--border)", fontSize: 11, color: "var(--muted)" }}>
                <div>Schedule</div>
                <div style={{ marginTop: 4 }}>
                  {schedule.last_refresh && (
                    <div>Refreshed: {timeAgo(schedule.last_refresh)}</div>
                  )}
                  {nextRunLabel(schedule) && (
                    <div style={{ marginTop: 2 }}>Next: {nextRunLabel(schedule)}</div>
                  )}
                </div>
              </div>
            )}

            {user && (
              <div style={{ padding: "12px 16px", borderTop: "1px solid var(--border)", fontSize: 12 }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <div>
                    <div style={{ color: "var(--text)", fontWeight: 600 }}>{user.display_name || user.username}</div>
                    {user.is_admin && (
                      <span style={{
                        fontSize: 10, color: "var(--accent)", fontWeight: 700,
                        background: "rgba(88, 166, 255, 0.1)",
                        padding: "1px 6px", borderRadius: 4, marginTop: 2, display: "inline-block",
                      }}>ADMIN</span>
                    )}
                  </div>
                  <button onClick={handleLogout} style={{
                    background: "none", border: "none", color: "var(--muted)",
                    cursor: "pointer", fontSize: 12, padding: "4px 8px",
                  }} title="Sign out">Logout</button>
                </div>
              </div>
            )}
          </aside>

          <SlipBuilderProvider>
            <main style={{ flex: 1, overflow: "auto", padding: "24px 28px" }}>
              {children}
            </main>
            <SlipBuilderPanel />
          </SlipBuilderProvider>
        </div>
      </body>
    </html>
  );
}
