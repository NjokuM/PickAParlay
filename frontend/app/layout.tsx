"use client";

import "./globals.css";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api, Credits } from "@/lib/api";

const NAV = [
  { href: "/",          label: "Tonight",   icon: "🏀" },
  { href: "/slips",     label: "Slips",     icon: "🎯" },
  { href: "/ladder",    label: "Ladder",    icon: "🪜" },
  { href: "/history",   label: "History",   icon: "📋" },
  { href: "/analytics", label: "Analytics", icon: "📈" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [credits, setCredits] = useState<Credits | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    api.credits().then(setCredits).catch(() => {});
  }, []);

  return (
    <html lang="en">
      <head>
        <title>PickAParlay</title>
        <meta name="description" content="NBA Bet Builder" />
      </head>
      <body style={{ margin: 0 }}>
        <div style={{ display: "flex", minHeight: "100vh" }}>
          {/* ── Sidebar ── */}
          <aside style={{
            width: 200,
            background: "var(--surface)",
            borderRight: "1px solid var(--border)",
            display: "flex",
            flexDirection: "column",
            padding: "0",
            flexShrink: 0,
          }}>
            {/* Logo */}
            <div style={{
              padding: "20px 16px 16px",
              borderBottom: "1px solid var(--border)",
            }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: "var(--accent)" }}>
                PickAParlay
              </div>
              <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>
                NBA Bet Builder
              </div>
            </div>

            {/* Nav links */}
            <nav style={{ flex: 1, padding: "8px 0" }}>
              {NAV.map(({ href, label, icon }) => {
                const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
                return (
                  <Link
                    key={href}
                    href={href}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                      padding: "10px 16px",
                      color: active ? "var(--text)" : "var(--muted)",
                      background: active ? "var(--surface2)" : "transparent",
                      borderLeft: active ? "2px solid var(--accent)" : "2px solid transparent",
                      textDecoration: "none",
                      fontSize: 14,
                      transition: "all 0.1s",
                    }}
                  >
                    <span>{icon}</span>
                    <span>{label}</span>
                  </Link>
                );
              })}
            </nav>

            {/* Credits */}
            {credits && (
              <div style={{
                padding: "12px 16px",
                borderTop: "1px solid var(--border)",
                fontSize: 11,
                color: "var(--muted)",
              }}>
                <div>Odds API</div>
                <div style={{ marginTop: 4 }}>
                  <div style={{
                    height: 4,
                    background: "var(--surface2)",
                    borderRadius: 2,
                    overflow: "hidden",
                  }}>
                    <div style={{
                      width: `${(credits.used / credits.total) * 100}%`,
                      height: "100%",
                      background: credits.remaining < 50 ? "var(--red)" : "var(--accent)",
                      transition: "width 0.3s",
                    }} />
                  </div>
                  <div style={{ marginTop: 4 }}>
                    {credits.used}/{credits.total} used · {credits.remaining} left
                  </div>
                </div>
              </div>
            )}
          </aside>

          {/* ── Main ── */}
          <main style={{ flex: 1, overflow: "auto", padding: "24px 28px" }}>
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
