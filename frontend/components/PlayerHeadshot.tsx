"use client";

import { useState } from "react";

const NBA_HEADSHOT_URL = "https://cdn.nba.com/headshots/nba/latest/260x190";

/**
 * Circular NBA player headshot fetched from the NBA CDN.
 * Falls back to a generic person silhouette on error or missing ID.
 */
export function PlayerHeadshot({
  playerId,
  size = 32,
}: {
  playerId: number | null | undefined;
  size?: number;
}) {
  const [errored, setErrored] = useState(false);

  if (!playerId || errored) {
    return (
      <div
        style={{
          width: size,
          height: size,
          borderRadius: "50%",
          background: "var(--surface2)",
          border: "1px solid var(--border)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
          overflow: "hidden",
        }}
      >
        <svg
          width={size * 0.55}
          height={size * 0.55}
          viewBox="0 0 24 24"
          fill="var(--muted)"
        >
          <path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z" />
        </svg>
      </div>
    );
  }

  return (
    <img
      src={`${NBA_HEADSHOT_URL}/${playerId}.png`}
      alt=""
      width={size}
      height={size}
      style={{
        borderRadius: "50%",
        objectFit: "cover",
        flexShrink: 0,
        background: "var(--surface2)",
        border: "1px solid var(--border)",
      }}
      onError={() => setErrored(true)}
    />
  );
}
