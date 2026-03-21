#!/bin/sh
# PickAParlay — Start all services
# 1. uvicorn (FastAPI backend) on :8000
# 2. next start (frontend) on :3000
# 3. caddy (reverse proxy) on :8080 (foreground)

set -e

# Ensure data directories exist
mkdir -p "$CACHE_DIR"

echo "[start] Starting PickAParlay..."
echo "[start] Database: $DATABASE_PATH"
echo "[start] Cache: $CACHE_DIR"

# Start FastAPI backend
echo "[start] Starting backend on :8000..."
uvicorn backend.app:app --host 0.0.0.0 --port 8000 --workers 1 &
BACKEND_PID=$!

# Start Next.js frontend (standalone mode)
echo "[start] Starting frontend on :3000..."
cd /app/frontend-standalone
PORT=3000 HOSTNAME=0.0.0.0 node server.js &
FRONTEND_PID=$!
cd /app

# Wait for both services to be ready
echo "[start] Waiting for services..."
sleep 3

# Start Caddy (foreground — keeps container alive)
echo "[start] Starting Caddy proxy on :8080..."
caddy run --config /app/Caddyfile

# If Caddy exits, clean up
kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
