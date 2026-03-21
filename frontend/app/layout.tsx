"use client";

import "./globals.css";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, Credits } from "@/lib/api";
import { SlipBuilderProvider } from "@/lib/slip-builder-context";
import SlipBuilderPanel from "@/components/SlipBuilderPanel";
import { getUser, isLoggedIn, clearAuth, isAdmin, AuthUser } from "@/lib/auth";

const NAV = [
  { href: "/",          label: "Tonight",   icon: "\u{1F3C0}" },
  { href: "/slips",     label: "Slips",     icon: "\u{1F3AF}" },
  { href: "/ladder",    label: "Ladder",    icon: "\u{1FA9C}" },
  { href: "/history",      label: "History",      icon: "\u{1F4CB}" },
  { href: "/prop-results", label: "Prop Results", icon: "\u{1F4CA}" },
  { href: "/analytics",    label: "Analytics",    icon: "\u{1F4C8}" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [credits, setCredits] = useState<Credits | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);

  // Check auth on mount
  useEffect(() => {
    if (pathname === "/login") {
      setAuthChecked(true);
      return;
    }
    if (!isLoggedIn()) {
      router.push("/login");
      return;
    }
    setUser(getUser());
    setAuthChecked(true);
    api.credits().then(setCredits).catch(() => {});
  }, [pathname, router]);

  // Login page gets its own layout (no sidebar)
  if (pathname === "/login") {
    return (
      <html lang="en">
        <head>
          <title>PickAParlay - Login</title>
          <meta name="description" content="NBA Bet Builder" />
        </head>
        <body style={{ margin: 0 }}>{children}</body>
      </html>
    );
  }

  // Don't render anything until auth is checked (prevents flash)
  if (!authChecked) {
    return (
      <html lang="en">
        <head><title>PickAParlay</title></head>
        <body style={{ margin: 0, background: "#0d1117" }} />
      </html>
    );
  }

  function handleLogout() {
    clearAuth();
    router.push("/login");
  }

  return (
    <html lang="en">
      <head>
        <title>PickAParlay</title>
        <meta name="description" content="NBA Bet Builder" />
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
            {/* Logo */}
            <div style={{
              padding: "20px 16px 16px",
              borderBottom: "1px solid var(--border)",
            }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: "var(--accent)" }}>
                PickAParlay
              </div>
              <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>
                NBA Prop Analytics
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

            {/* Credits (admin only) */}
            {credits && user?.is_admin && (
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

            {/* User section */}
            {user && (
              <div style={{
                padding: "12px 16px",
                borderTop: "1px solid var(--border)",
                fontSize: 12,
              }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <div>
                    <div style={{ color: "var(--text)", fontWeight: 600 }}>
                      {user.display_name || user.username}
                    </div>
                    {user.is_admin && (
                      <span style={{
                        fontSize: 10, color: "var(--accent)", fontWeight: 700,
                        background: "rgba(88, 166, 255, 0.1)",
                        padding: "1px 6px", borderRadius: 4, marginTop: 2, display: "inline-block",
                      }}>
                        ADMIN
                      </span>
                    )}
                  </div>
                  <button
                    onClick={handleLogout}
                    style={{
                      background: "none", border: "none", color: "var(--muted)",
                      cursor: "pointer", fontSize: 12, padding: "4px 8px",
                    }}
                    title="Sign out"
                  >
                    Logout
                  </button>
                </div>
              </div>
            )}
          </aside>

          {/* Main */}
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
