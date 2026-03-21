# ============================================================
# PickAParlay — Multi-stage Docker build
# Stage 1: Build Next.js frontend (standalone output)
# Stage 2: Python runtime with frontend + backend + Caddy
# ============================================================

# ── Stage 1: Frontend build ──
FROM node:20-slim AS frontend-build
WORKDIR /build

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund

COPY frontend/ .
# Production API calls go to same origin (Caddy proxies /api to uvicorn)
ENV NEXT_PUBLIC_API_URL=""
RUN npm run build


# ── Stage 2: Production runtime ──
FROM python:3.12-slim
WORKDIR /app

# Install Node.js 20 (for next start) + Caddy
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl gnupg ca-certificates && \
    # Node.js
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    # Caddy (auto-detect architecture)
    CADDY_ARCH=$(dpkg --print-architecture) && \
    curl -fsSL "https://caddyserver.com/api/download?os=linux&arch=${CADDY_ARCH}" -o /usr/local/bin/caddy && \
    chmod +x /usr/local/bin/caddy && \
    # Cleanup
    apt-get purge -y gnupg && apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend + shared source
COPY config.py .
COPY backend/ backend/
COPY src/ src/

# Copy built frontend (standalone output)
COPY --from=frontend-build /build/.next/standalone ./frontend-standalone/
COPY --from=frontend-build /build/.next/static ./frontend-standalone/.next/static/
COPY --from=frontend-build /build/public ./frontend-standalone/public/

# Caddy config + entrypoint
COPY Caddyfile .
COPY start.sh .
RUN chmod +x start.sh

# Data directory (mount a persistent volume here in production)
RUN mkdir -p /data

# Environment defaults
ENV DATABASE_PATH=/data/pickaparlay.db \
    CACHE_DIR=/data/cache \
    JWT_SECRET_KEY=change-me-in-production \
    INVITE_CODE=pickaparlay2026 \
    ODDS_API_KEY="" \
    CORS_ORIGINS="*"

EXPOSE 8080

CMD ["./start.sh"]
