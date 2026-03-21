"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { setAuth, AuthUser } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      if (mode === "login") {
        const res = await api.auth.login({ username, password });
        const user: AuthUser = {
          user_id: res.user_id,
          username: res.username,
          display_name: res.display_name,
          is_admin: res.is_admin,
        };
        setAuth(res.access_token, user);
        router.push("/");
      } else {
        const res = await api.auth.register({
          username,
          password,
          display_name: displayName || undefined,
          invite_code: inviteCode,
        });
        const user: AuthUser = {
          user_id: res.user_id,
          username: res.username,
          display_name: res.display_name,
          is_admin: res.is_admin,
        };
        setAuth(res.access_token, user);
        router.push("/");
      }
    } catch (err: unknown) {
      const msg = (err as Error).message;
      // Try to parse JSON error detail from FastAPI
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

  return (
    <div style={{
      minHeight: "100vh",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      background: "#0d1117",
    }}>
      <div style={{
        width: 380,
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 12,
        padding: 32,
      }}>
        {/* Logo */}
        <div style={{ textAlign: "center", marginBottom: 28 }}>
          <h1 style={{ fontSize: 24, fontWeight: 800, color: "var(--accent)", margin: 0 }}>
            PickAParlay
          </h1>
          <p style={{ color: "var(--muted)", fontSize: 13, margin: "4px 0 0" }}>
            NBA Prop Analytics
          </p>
        </div>

        {/* Mode tabs */}
        <div style={{ display: "flex", gap: 0, marginBottom: 20, borderRadius: 8, overflow: "hidden", border: "1px solid var(--border)" }}>
          <button
            onClick={() => setMode("login")}
            style={{
              flex: 1, padding: "10px 0", border: "none", cursor: "pointer",
              background: mode === "login" ? "var(--accent)" : "var(--surface2)",
              color: mode === "login" ? "#0d1117" : "var(--muted)",
              fontWeight: mode === "login" ? 700 : 400, fontSize: 14,
            }}
          >
            Sign In
          </button>
          <button
            onClick={() => setMode("register")}
            style={{
              flex: 1, padding: "10px 0", border: "none", cursor: "pointer",
              background: mode === "register" ? "var(--accent)" : "var(--surface2)",
              color: mode === "register" ? "#0d1117" : "var(--muted)",
              fontWeight: mode === "register" ? 700 : 400, fontSize: 14,
            }}
          >
            Register
          </button>
        </div>

        {error && (
          <div style={{
            background: "#2d1e1e", border: "1px solid #f85149", borderRadius: 6,
            padding: "8px 12px", marginBottom: 16, color: "#f85149", fontSize: 13,
          }}>
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 14 }}>
            <label style={{ display: "block", fontSize: 13, color: "var(--muted)", marginBottom: 4 }}>
              Username
            </label>
            <input
              type="text"
              value={username}
              onChange={e => setUsername(e.target.value)}
              required
              autoComplete="username"
              style={{
                width: "100%", padding: "10px 12px", borderRadius: 6,
                border: "1px solid var(--border)", background: "var(--surface2)",
                color: "var(--text)", fontSize: 14, outline: "none",
                boxSizing: "border-box",
              }}
            />
          </div>

          {mode === "register" && (
            <div style={{ marginBottom: 14 }}>
              <label style={{ display: "block", fontSize: 13, color: "var(--muted)", marginBottom: 4 }}>
                Display Name (optional)
              </label>
              <input
                type="text"
                value={displayName}
                onChange={e => setDisplayName(e.target.value)}
                autoComplete="name"
                style={{
                  width: "100%", padding: "10px 12px", borderRadius: 6,
                  border: "1px solid var(--border)", background: "var(--surface2)",
                  color: "var(--text)", fontSize: 14, outline: "none",
                  boxSizing: "border-box",
                }}
              />
            </div>
          )}

          <div style={{ marginBottom: 14 }}>
            <label style={{ display: "block", fontSize: 13, color: "var(--muted)", marginBottom: 4 }}>
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              style={{
                width: "100%", padding: "10px 12px", borderRadius: 6,
                border: "1px solid var(--border)", background: "var(--surface2)",
                color: "var(--text)", fontSize: 14, outline: "none",
                boxSizing: "border-box",
              }}
            />
          </div>

          {mode === "register" && (
            <div style={{ marginBottom: 14 }}>
              <label style={{ display: "block", fontSize: 13, color: "var(--muted)", marginBottom: 4 }}>
                Invite Code
              </label>
              <input
                type="text"
                value={inviteCode}
                onChange={e => setInviteCode(e.target.value)}
                required
                placeholder="Enter your invite code"
                style={{
                  width: "100%", padding: "10px 12px", borderRadius: 6,
                  border: "1px solid var(--border)", background: "var(--surface2)",
                  color: "var(--text)", fontSize: 14, outline: "none",
                  boxSizing: "border-box",
                }}
              />
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            style={{
              width: "100%", padding: "12px 0", borderRadius: 6, border: "none",
              background: loading ? "var(--surface2)" : "var(--accent)",
              color: loading ? "var(--muted)" : "#0d1117",
              fontSize: 15, fontWeight: 700, cursor: loading ? "not-allowed" : "pointer",
              marginTop: 4,
            }}
          >
            {loading ? "..." : mode === "login" ? "Sign In" : "Create Account"}
          </button>
        </form>
      </div>
    </div>
  );
}
